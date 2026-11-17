/*
 * Phase 8 - RX2 Morse IR Receiver + Numbered Text-File Reception
 * ESP32 / ESP-IDF v5.5.6
 *
 * RX2 address : 02
 * IR input    : GPIO16 (10 kOhm external pull-up to 3.3 V)
 * OLED        : SSD1306 128x64 I2C, SDA GPIO21, SCL GPIO22, address 0x3C
 *
 * Valid message displayed only if addressed to 02 AND checksum passes.
 * Adds Phase 8 file packet buffering and reconstruction (no TX ACK yet).
 * Suspected interruption rejects frame and recovers automatically after
 * 3 seconds of warning and 2 seconds of quiet IR input.
 */

#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <ctype.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_timer.h"
#include "esp_err.h"
#include "esp_attr.h"
#include "phase8_packet_protocol.h"

#define RX_PIN              GPIO_NUM_16
#define OLED_ADDRESS        0x3C
#define MAX_FRAME           128
#define MAX_MESSAGE         80
#define DOT_DASH_LIMIT_US   400000
#define LETTER_GAP_US       450000
#define WORD_GAP_US         1100000
#define FRAME_TIMEOUT_US    3200000
#define RECOVERY_TIME_US    3000000
#define RECOVERY_QUIET_US   2000000

typedef struct {
    int level;
    int64_t time_us;
} ir_edge_t;

static QueueHandle_t edge_queue;
static i2c_master_dev_handle_t oled;
static uint8_t framebuffer[1024];
static char received_frame[MAX_FRAME];
static size_t frame_len = 0;
static char morse_symbols[8];
static size_t morse_len = 0;
static bool receiving = false;
static int previous_level = 1;
static int64_t previous_time = 0;
static int64_t last_edge_time = 0;

static phase8_file_state_t phase8_file = {0};

static bool recovery_active = false;
static int64_t recovery_started_us = 0;
static int64_t recovery_last_edge_us = 0;

static const char *morse_table[36] = {
    ".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....", "..", ".---",
    "-.-", ".-..", "--", "-.", "---", ".--.", "--.-", ".-.", "...", "-",
    "..-", "...-", ".--", "-..-", "-.--", "--..",
    "-----", ".----", "..---", "...--", "....-", ".....", "-....",
    "--...", "---..", "----."
};
static const char morse_chars[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

static const uint8_t letters[26][5] = {
    {0x7E,0x11,0x11,0x11,0x7E}, {0x7F,0x49,0x49,0x49,0x36},
    {0x3E,0x41,0x41,0x41,0x22}, {0x7F,0x41,0x41,0x22,0x1C},
    {0x7F,0x49,0x49,0x49,0x41}, {0x7F,0x09,0x09,0x09,0x01},
    {0x3E,0x41,0x49,0x49,0x7A}, {0x7F,0x08,0x08,0x08,0x7F},
    {0x00,0x41,0x7F,0x41,0x00}, {0x20,0x40,0x41,0x3F,0x01},
    {0x7F,0x08,0x14,0x22,0x41}, {0x7F,0x40,0x40,0x40,0x40},
    {0x7F,0x02,0x0C,0x02,0x7F}, {0x7F,0x04,0x08,0x10,0x7F},
    {0x3E,0x41,0x41,0x41,0x3E}, {0x7F,0x09,0x09,0x09,0x06},
    {0x3E,0x41,0x51,0x21,0x5E}, {0x7F,0x09,0x19,0x29,0x46},
    {0x46,0x49,0x49,0x49,0x31}, {0x01,0x01,0x7F,0x01,0x01},
    {0x3F,0x40,0x40,0x40,0x3F}, {0x1F,0x20,0x40,0x20,0x1F},
    {0x7F,0x20,0x18,0x20,0x7F}, {0x63,0x14,0x08,0x14,0x63},
    {0x03,0x04,0x78,0x04,0x03}, {0x61,0x51,0x49,0x45,0x43}
};

static const uint8_t digits[10][5] = {
    {0x3E,0x51,0x49,0x45,0x3E}, {0x00,0x42,0x7F,0x40,0x00},
    {0x42,0x61,0x51,0x49,0x46}, {0x21,0x41,0x45,0x4B,0x31},
    {0x18,0x14,0x12,0x7F,0x10}, {0x27,0x45,0x45,0x45,0x39},
    {0x3C,0x4A,0x49,0x49,0x30}, {0x01,0x71,0x09,0x05,0x03},
    {0x36,0x49,0x49,0x49,0x36}, {0x06,0x49,0x49,0x29,0x1E}
};

static void oled_cmd(uint8_t command)
{
    uint8_t packet[] = {0x00, command};
    ESP_ERROR_CHECK(i2c_master_transmit(oled, packet, sizeof(packet), 1000));
}

static void oled_init(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = GPIO_NUM_21,
        .scl_io_num = GPIO_NUM_22,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = OLED_ADDRESS,
        .scl_speed_hz = 100000
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &oled));

    const uint8_t commands[] = {
        0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
        0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12,
        0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6,
        0x2E, 0xAF
    };
    for (size_t i = 0; i < sizeof(commands); i++) {
        oled_cmd(commands[i]);
    }
}

static void oled_character(int x, int page, char ch)
{
    static const uint8_t colon[5] = {0x00,0x36,0x36,0x00,0x00};
    static const uint8_t dash[5] = {0x08,0x08,0x08,0x08,0x08};
    static const uint8_t question[5] = {0x02,0x01,0x51,0x09,0x06};
    const uint8_t *glyph = NULL;

    if (ch >= 'A' && ch <= 'Z') glyph = letters[ch - 'A'];
    else if (ch >= '0' && ch <= '9') glyph = digits[ch - '0'];
    else if (ch == ':') glyph = colon;
    else if (ch == '-') glyph = dash;
    else if (ch == '?') glyph = question;

    if (!glyph || x < 0 || x + 5 > 128 || page < 0 || page > 7) return;
    for (int i = 0; i < 5; i++) {
        framebuffer[page * 128 + x + i] = glyph[i];
    }
}

static void oled_text(int x, int page, const char *text)
{
    while (*text && x + 5 <= 128) {
        oled_character(x, page, *text++);
        x += 6;
    }
}

static void oled_refresh(void)
{
    const uint8_t addr_cmds[] = {0x00, 0x21, 0x00, 0x7F, 0x22, 0x00, 0x07};
    ESP_ERROR_CHECK(i2c_master_transmit(oled, addr_cmds, sizeof(addr_cmds), 1000));

    for (int i = 0; i < (int)sizeof(framebuffer); i += 16) {
        uint8_t packet[17];
        packet[0] = 0x40;
        memcpy(packet + 1, framebuffer + i, 16);
        ESP_ERROR_CHECK(i2c_master_transmit(oled, packet, sizeof(packet), 1000));
    }
}

/* A message is visible on OLED ONLY after address 02 AND checksum match. */
static void display_status(const char *status, const char *message,
                           const char *result)
{
    memset(framebuffer, 0, sizeof(framebuffer));
    oled_text(0, 0, "RX2 ADDR:02");
    oled_text(0, 1, status);

    bool valid = (strcmp(status, "RX2 RECEIVED") == 0 ||
                  strcmp(status, "FILE COMPLETE") == 0) &&
                 strcmp(result, "CHECKSUM OK") == 0;
    if (valid && message) {
        size_t length = strlen(message);
        for (int row = 0; row < 5; row++) {
            size_t start = (size_t)row * 20;
            if (start >= length) break;
            char line[21] = {0};
            size_t count = length - start;
            if (count > 20) count = 20;
            memcpy(line, message + start, count);
            oled_text(0, row + 2, line);
        }
    }
    oled_text(0, 7, result);
    oled_refresh();
}

static void IRAM_ATTR ir_interrupt(void *arg)
{
    (void)arg;
    ir_edge_t event = {
        .level = gpio_get_level(RX_PIN),
        .time_us = esp_timer_get_time()
    };
    BaseType_t wake = pdFALSE;
    xQueueSendFromISR(edge_queue, &event, &wake);
    if (wake) portYIELD_FROM_ISR();
}

static char decode_morse(const char *symbols)
{
    for (int i = 0; i < 36; i++) {
        if (strcmp(symbols, morse_table[i]) == 0) return morse_chars[i];
    }
    return '?';
}

static void append_character(char ch)
{
    if (frame_len < MAX_FRAME - 1) {
        received_frame[frame_len++] = ch;
        received_frame[frame_len] = '\0';
    }
}

static void finish_letter(void)
{
    if (morse_len == 0) return;
    morse_symbols[morse_len] = '\0';
    char ch = decode_morse(morse_symbols);
    append_character(ch);
    printf("Decoded: %c | Frame: %s\n", ch, received_frame);
    morse_len = 0;
}

static void reset_receiver(void)
{
    frame_len = 0;
    morse_len = 0;
    received_frame[0] = '\0';
    morse_symbols[0] = '\0';
    receiving = false;
}

/* A malformed frame starts a temporary recovery, NOT a permanent lock. */
static void signal_interrupted(const char *reason)
{
    printf("\n================================\n");
    printf("RX2 SIGNAL INTERRUPTED\n");
    printf("Reason: %s\n", reason);
    printf("Current frame rejected\n");
    printf("Automatic recovery started\n");
    printf("RX2_EVENT:SIGNAL_INTERRUPTED\n");
    printf("================================\n");

    recovery_active = true;
    recovery_started_us = esp_timer_get_time();
    recovery_last_edge_us = recovery_started_us;

    reset_receiver();
    /* An incomplete file must not survive damaged optical data. */
    if (phase8_file.active) {
        printf("RX2 FILE: PARTIAL TRANSFER DISCARDED\n");
        phase8_reset_file(&phase8_file);
    }
    display_status("SIGNAL INTERRUPTED", "", "FRAME REJECTED");
}

static void validate_frame(void)
{
    finish_letter();
    printf("\n================================\n");
    printf("RX2 RECEIVED: [%s]\n", received_frame);

    if (frame_len < 5) {
        printf("RESULT: INVALID FRAME\n");
        signal_interrupted("INCOMPLETE FRAME");
        return;
    }

    char address[3] = {received_frame[0], received_frame[1], '\0'};
    size_t checksum_pos = frame_len - 3;

    for (size_t i = checksum_pos; i < frame_len; i++) {
        if (!isdigit((unsigned char)received_frame[i])) {
            printf("RESULT: INVALID CHECKSUM FIELD\n");
            signal_interrupted("INVALID CHECKSUM FIELD");
            return;
        }
    }

    int received_checksum =
        (received_frame[checksum_pos] - '0') * 100 +
        (received_frame[checksum_pos + 1] - '0') * 10 +
        (received_frame[checksum_pos + 2] - '0');

    unsigned int sum = 0;
    for (size_t i = 0; i < checksum_pos; i++) {
        sum += (unsigned char)received_frame[i];
    }
    int calculated_checksum = (int)(sum % 256);

    size_t message_length = checksum_pos - 2;
    if (message_length > MAX_MESSAGE) {
        printf("RESULT: MESSAGE TOO LONG\n");
        signal_interrupted("FRAME TOO LONG");
        return;
    }

    char message[MAX_MESSAGE + 1] = {0};
    memcpy(message, received_frame + 2, message_length);

    printf("Address: %s\n", address);
    printf("Message: %s\n", message);
    printf("Received checksum: %03d\n", received_checksum);
    printf("Calculated checksum: %03d\n", calculated_checksum);

    if (strcmp(address, "02") != 0) {
        printf("RESULT: WRONG ADDRESS - REJECTED\n");
        display_status("WRONG ADDRESS", "", "REJECTED");
    } else if (received_checksum != calculated_checksum) {
        printf("RESULT: CHECKSUM FAILED\n");
        signal_interrupted("CHECKSUM MISMATCH");
    } else if (phase8_looks_like_file_frame(received_frame, frame_len)) {
        /* The checked frame contains: 02 F SSS TTT LL PAYLOAD CCC
           SSS sequence, TTT total, LL payload length, CCC ASCII checksum.
           The packet parser independently rechecks the whole frame. */
        phase8_packet_result_t r = phase8_accept_frame(
            &phase8_file, received_frame, frame_len, "02");
        if (r.status == PHASE8_PACKET_REJECTED) {
            printf("RESULT: FILE PACKET REJECTED - %s\n", r.detail);
            signal_interrupted("INVALID FILE PACKET");
            return;
        } else if (r.status == PHASE8_PACKET_DUPLICATE) {
            printf("RX2 FILE: DUPLICATE PACKET %03u IGNORED\n", r.sequence);
            display_status("FILE DUPLICATE", "", "RECEIVING");
        } else if (r.status == PHASE8_PACKET_ACCEPTED) {
            printf("RX2 FILE PACKET %03u/%03u ACCEPTED; STORED %u/%u\n",
                   r.sequence, r.total, r.received, r.total);
            printf("RX2_EVENT:FILE_PACKET_OK\n");
            display_status("FILE PACKET OK", "", "RECEIVING");
        } else if (r.status == PHASE8_PACKET_COMPLETE) {
            printf("RX2 FILE PACKET %03u/%03u ACCEPTED\n", r.sequence, r.total);
            printf("RX2 FILE COMPLETE: %u PACKETS, %u CHARACTERS\n",
                   r.total, (unsigned int)phase8_file.reconstructed_length);
            printf("RX2 FILE TEXT BEGIN\n%s\nRX2 FILE TEXT END\n", phase8_file.text);
            printf("RX2_EVENT:FILE_COMPLETE\n");
            /* OLED can show at most the first 100 chars; UART logs full file. */
            display_status("FILE COMPLETE", phase8_file.text, "CHECKSUM OK");
            phase8_reset_file(&phase8_file);
        }
    } else {
        /* Preserve the original ordinary-addressed-message behavior. */
        if (phase8_file.active) {
            printf("RX2 FILE: INCOMPLETE FILE ABORTED BY TEXT MESSAGE\n");
            phase8_reset_file(&phase8_file);
        }
        printf("RESULT: CHECKSUM OK - ACCEPTED\n");
        display_status("RX2 RECEIVED", message, "CHECKSUM OK");
    }
    printf("================================\n\n");
}

static void handle_edge(ir_edge_t event)
{
    if (event.level == previous_level) return;
    int64_t duration = event.time_us - previous_time;

    if (previous_level == 1 && event.level == 0) {
        /* HIGH interval has ended: check letter/word gap. */
        if (receiving && duration >= LETTER_GAP_US) {
            finish_letter();
            if (duration >= WORD_GAP_US && frame_len > 0 &&
                received_frame[frame_len - 1] != ' ') {
                append_character(' ');
            }
            display_status("RECEIVING", "", "CHECK PENDING");
        }
        if (!receiving) {
            receiving = true;
            display_status("RECEIVING", "", "CHECK PENDING");
        }
    } else if (previous_level == 0 && event.level == 1) {
        /* LOW pulse has ended: distinguish dot from dash. */
        if (duration >= 80000 && duration <= 1100000) {
            char symbol = duration < DOT_DASH_LIMIT_US ? '.' : '-';
            if (morse_len < sizeof(morse_symbols) - 1) {
                morse_symbols[morse_len++] = symbol;
            }
        }
    }

    previous_level = event.level;
    previous_time = event.time_us;
    last_edge_time = event.time_us;
}

void app_main(void)
{
    printf("\n================================\n");
    printf("PHASE 8 - RX2 FILE RECEIVER\n");
    printf("Receiver Address: 02\n");
    printf("IR GPIO: 16\n");
    printf("OLED: 0x3C\n");
    printf("Message display: VALID FRAMES ONLY\n");
    printf("Automatic recovery: ENABLED\n");
    printf("File packets: F + sequence + total + length + payload\n");
    printf("================================\n");

    oled_init();
    display_status("IR READY", "", "WAITING");

    edge_queue = xQueueCreate(256, sizeof(ir_edge_t));
    ESP_ERROR_CHECK(edge_queue ? ESP_OK : ESP_ERR_NO_MEM);

    gpio_config_t io = {
        .pin_bit_mask = 1ULL << RX_PIN,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_ANYEDGE
    };
    ESP_ERROR_CHECK(gpio_config(&io));
    previous_level = gpio_get_level(RX_PIN);
    previous_time = esp_timer_get_time();
    last_edge_time = previous_time;

    ESP_ERROR_CHECK(gpio_install_isr_service(0));
    ESP_ERROR_CHECK(gpio_isr_handler_add(RX_PIN, ir_interrupt, NULL));
    printf("RX2 READY - WAITING FOR IR\n");

    while (1) {
        ir_edge_t event;
        bool event_received =
            xQueueReceive(edge_queue, &event, pdMS_TO_TICKS(50)) == pdTRUE;
        int64_t now = esp_timer_get_time();

        if (recovery_active) {
            /* Ignore any leftover IR pulses from the rejected frame. */
            if (event_received) recovery_last_edge_us = event.time_us;
            bool warning_elapsed = now - recovery_started_us >= RECOVERY_TIME_US;
            bool signal_quiet = now - recovery_last_edge_us >= RECOVERY_QUIET_US;
            bool input_idle = gpio_get_level(RX_PIN) == 1;

            if (warning_elapsed && signal_quiet && input_idle) {
                xQueueReset(edge_queue);
                reset_receiver();
                previous_level = 1;
                previous_time = now;
                last_edge_time = now;
                recovery_active = false;
                display_status("IR READY", "", "WAITING");
                printf("RX2 AUTO RECOVERY COMPLETE\n");
                printf("RX2 READY - WAITING FOR IR\n");
            }
            continue;
        }

        if (event_received) handle_edge(event);
        now = esp_timer_get_time();
        if (receiving && previous_level == 1 &&
            now - last_edge_time >= FRAME_TIMEOUT_US) {
            validate_frame();
            reset_receiver();
        }
    }
}
