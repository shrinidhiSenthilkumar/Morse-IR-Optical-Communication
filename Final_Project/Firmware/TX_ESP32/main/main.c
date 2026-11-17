#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <ctype.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "phase8_tx_file_parser.h"

#define TX_PIN GPIO_NUM_17

#define DOT_MS          200
#define DASH_MS         600
#define SYMBOL_GAP_MS   200
#define LETTER_GAP_MS   700
#define WORD_GAP_MS     1400

#define MAX_INPUT_LENGTH   128
#define MAX_MESSAGE_LENGTH 80
#define MAX_FRAME_LENGTH   120

typedef struct
{
    char character;
    const char *morse;
} morse_entry_t;

static const morse_entry_t morse_table[] =
{
    {'A', ".-"},
    {'B', "-..."},
    {'C', "-.-."},
    {'D', "-.."},
    {'E', "."},
    {'F', "..-."},
    {'G', "--."},
    {'H', "...."},
    {'I', ".."},
    {'J', ".---"},
    {'K', "-.-"},
    {'L', ".-.."},
    {'M', "--"},
    {'N', "-."},
    {'O', "---"},
    {'P', ".--."},
    {'Q', "--.-"},
    {'R', ".-."},
    {'S', "..."},
    {'T', "-"},
    {'U', "..-"},
    {'V', "...-"},
    {'W', ".--"},
    {'X', "-..-"},
    {'Y', "-.--"},
    {'Z', "--.."},

    {'0', "-----"},
    {'1', ".----"},
    {'2', "..---"},
    {'3', "...--"},
    {'4', "....-"},
    {'5', "....."},
    {'6', "-...."},
    {'7', "--..."},
    {'8', "---.."},
    {'9', "----."}
};

const char *get_morse(char c)
{
    int table_size =
        sizeof(morse_table) / sizeof(morse_table[0]);

    for (int i = 0; i < table_size; i++)
    {
        if (morse_table[i].character == c)
        {
            return morse_table[i].morse;
        }
    }

    return NULL;
}

uint8_t calculate_checksum(const char *data)
{
    uint16_t sum = 0;

    for (int i = 0; data[i] != '\0'; i++)
    {
        sum += (uint8_t)data[i];
    }

    return (uint8_t)(sum & 0xFF);
}

void send_dot(void)
{
    gpio_set_level(TX_PIN, 1);

    vTaskDelay(pdMS_TO_TICKS(DOT_MS));

    gpio_set_level(TX_PIN, 0);
}

void send_dash(void)
{
    gpio_set_level(TX_PIN, 1);

    vTaskDelay(pdMS_TO_TICKS(DASH_MS));

    gpio_set_level(TX_PIN, 0);
}

void send_morse_character(char c)
{
    if (c == ' ')
    {
        gpio_set_level(TX_PIN, 0);

        vTaskDelay(pdMS_TO_TICKS(WORD_GAP_MS));

        return;
    }

    const char *morse = get_morse(c);

    if (morse == NULL)
    {
        printf("Unsupported character skipped: %c\n", c);

        return;
    }

    printf("%c = %s\n", c, morse);

    for (int i = 0; morse[i] != '\0'; i++)
    {
        if (morse[i] == '.')
        {
            send_dot();
        }
        else if (morse[i] == '-')
        {
            send_dash();
        }

        if (morse[i + 1] != '\0')
        {
            vTaskDelay(pdMS_TO_TICKS(SYMBOL_GAP_MS));
        }
    }

    vTaskDelay(pdMS_TO_TICKS(LETTER_GAP_MS));
}

void transmit_frame(const char *frame)
{
    printf("\n");
    printf("====================================\n");
    printf("MORSE TRANSMISSION STARTED\n");
    printf("Frame: %s\n", frame);
    printf("====================================\n");

    for (int i = 0; frame[i] != '\0'; i++)
    {
        send_morse_character(frame[i]);
    }

    gpio_set_level(TX_PIN, 0);

    printf("====================================\n");
    printf("MORSE TRANSMISSION COMPLETE\n");
    printf("====================================\n");
}

void process_input(char *input)
{
    /* Phase 8 addition: FILE|<complete_file_packet> sends an already
       checksummed file frame EXACTLY as supplied; legacy commands retain
       the original address + message + checksum behavior unchanged. */
    if (strncmp(input, "FILE|", 5) == 0)
    {
        const char *file_frame = input + 5;
        char reason[96] = {0};
        if (!phase8_validate_file_packet(file_frame, reason, sizeof(reason)))
        {
            printf("\nPHASE 8 FILE PACKET REJECTED: %s\n", reason);
            return;
        }

        printf("\n====================================\n");
        printf("PHASE 8 FILE PACKET READY\n");
        printf("Raw frame   : %s\n", file_frame);
        printf("Raw length  : %u\n", (unsigned int)strlen(file_frame));
        printf("No second address or checksum will be added.\n");
        printf("====================================\n");
        transmit_frame(file_frame);
        return;
    }
    char *separator = strchr(input, '|');

    if (separator == NULL)
    {
        printf("\nINVALID FORMAT\n");
        printf("Use: ADDRESS|MESSAGE\n");
        printf("Example: 02|HELLO\n");

        return;
    }

    *separator = '\0';

    char *destination = input;
    char *message = separator + 1;

    if (strlen(destination) != 2)
    {
        printf("\nINVALID ADDRESS\n");
        printf("Address must contain exactly 2 characters.\n");

        return;
    }

    if (strlen(message) == 0)
    {
        printf("\nINVALID MESSAGE\n");
        printf("Message cannot be empty.\n");

        return;
    }

    if (strlen(message) > MAX_MESSAGE_LENGTH)
    {
        printf("\nMESSAGE TOO LONG\n");

        return;
    }

    for (int i = 0; destination[i] != '\0'; i++)
    {
        destination[i] =
            (char)toupper((unsigned char)destination[i]);
    }

    for (int i = 0; message[i] != '\0'; i++)
    {
        message[i] =
            (char)toupper((unsigned char)message[i]);

        if (!(message[i] == ' ' ||
              (message[i] >= 'A' && message[i] <= 'Z') ||
              (message[i] >= '0' && message[i] <= '9')))
        {
            printf("\nINVALID CHARACTER: %c\n", message[i]);
            printf("Use only A-Z, 0-9 and spaces.\n");

            return;
        }
    }

    char checksum_data[MAX_FRAME_LENGTH];

    snprintf(
        checksum_data,
        sizeof(checksum_data),
        "%s%s",
        destination,
        message
    );

    uint8_t checksum =
        calculate_checksum(checksum_data);

    char final_frame[MAX_FRAME_LENGTH];

    snprintf(
        final_frame,
        sizeof(final_frame),
        "%s%s%03u",
        destination,
        message,
        checksum
    );

    printf("\n");
    printf("====================================\n");
    printf("PHASE 7 FRAME READY\n");
    printf("Destination : %s\n", destination);
    printf("Message     : %s\n", message);
    printf("Checksum    : %03u\n", checksum);
    printf("Final frame : %s\n", final_frame);
    printf("====================================\n");

    transmit_frame(final_frame);
}

void app_main(void)
{
    gpio_reset_pin(TX_PIN);
    gpio_set_direction(TX_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(TX_PIN, 0);

    char input_buffer[MAX_INPUT_LENGTH];
    int index = 0;

    printf("\n");
    printf("====================================\n");
    printf("PHASE 7 UART TO MORSE IR TX\n");
    printf("Format: ADDRESS|MESSAGE\n");
    printf("Example: 02|HELLO\n");
    printf("File packet: FILE|02F00100240...220\n");
    printf("Allowed: A-Z, 0-9 and spaces\n");
    printf("====================================\n");

    printf("\nEnter command: ");
    fflush(stdout);

    while (1)
    {
        int ch = getchar();

        if (ch >= 0)
        {
            if ((ch == '\r') || (ch == '\n'))
            {
                if (index > 0)
                {
                    input_buffer[index] = '\0';

                    process_input(input_buffer);

                    index = 0;

                    printf("\nEnter command: ");
                    fflush(stdout);
                }
            }
            else
            {
                if (index < MAX_INPUT_LENGTH - 1)
                {
                    input_buffer[index++] = (char)ch;
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(20));
    }
}