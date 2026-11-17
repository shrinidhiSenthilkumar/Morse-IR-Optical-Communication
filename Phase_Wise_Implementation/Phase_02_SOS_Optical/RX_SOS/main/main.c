/* Reconstructed RX optical Morse test. GPIO16 active LOW when IR detected.
 * For actual phototransistor circuit verify polarity using Phase 1 first.
 * ISR -> FreeRTOS queue -> decoder task; no lengthy ISR logic.
 */
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_attr.h"
#define RX_PIN GPIO_NUM_16
#define DOT_DASH_THRESHOLD_US 400000
#define LETTER_GAP_US 450000
#define WORD_GAP_US 1100000
#define FRAME_DONE_US 3200000
static const char *morse_table[36] = {
    ".-","-...","-.-.","-..",".","..-.","--.","....","..",".---","-.-",".-..","--","-.","---",
    ".--.","--.-",".-.","...","-","..-","...-",".--","-..-","-.--","--..",
    "-----",".----","..---","...--","....-",".....","-....","--...","---..","----."
};
static const char characters[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

typedef struct { int level; int64_t timestamp; } edge_t;
static QueueHandle_t events;
static char symbols[8];
static size_t n_symbols;
static char frame[128];
static size_t n_frame;
static int last_level=1;
static int64_t pulse_start_us=0, last_pulse_end_us=0;
static bool active=false;
static void IRAM_ATTR isr_handler(void *arg) {
    (void)arg;
    edge_t e={gpio_get_level(RX_PIN),esp_timer_get_time()};
    BaseType_t waking=pdFALSE;
    xQueueSendFromISR(events,&e,&waking);
    if(waking) portYIELD_FROM_ISR();
}
static void append_frame(char c) {
    if(n_frame<sizeof(frame)-1){frame[n_frame++]=c;frame[n_frame]=0;}
}
static void finish_letter(void) {
    if(!n_symbols) return;
    symbols[n_symbols]=0;
    char found='?';
    for(int i=0;i<36;++i) if(!strcmp(symbols,morse_table[i])) {found=characters[i];break;}
    append_frame(found);
    printf("Letter: %c | %s\n",found,frame);
    n_symbols=0;
}
static void finish_frame(void) {
    finish_letter();
    printf("PHASE 2 decoded Morse text: %s\n",frame);
    n_frame=0;frame[0]=0;active=false;
}
void app_main(void) {
    gpio_config_t cfg={0};
    cfg.pin_bit_mask=1ULL<<RX_PIN;
    cfg.mode=GPIO_MODE_INPUT;
    cfg.pull_up_en=GPIO_PULLUP_ENABLE;
    cfg.intr_type=GPIO_INTR_ANYEDGE;
    ESP_ERROR_CHECK(gpio_config(&cfg));
    events=xQueueCreate(128,sizeof(edge_t));
    if(!events){puts("Queue allocation failed");return;}
    ESP_ERROR_CHECK(gpio_install_isr_service(0));
    ESP_ERROR_CHECK(gpio_isr_handler_add(RX_PIN,isr_handler,NULL));
    puts("Receiver ready. Check GPIO16 active-low sensor polarity.");
    while(1) {
        edge_t e;
        if(xQueueReceive(events,&e,pdMS_TO_TICKS(20))==pdTRUE) {
            if(e.level==last_level) continue;
            last_level=e.level;
            if(e.level==0) { // Falling edge: IR light starts
                if(active && last_pulse_end_us>0) {
                    int64_t gap=e.timestamp-last_pulse_end_us;
                    if(gap>=LETTER_GAP_US) finish_letter();
                    /* no word spaces in this phase */
                }
                pulse_start_us=e.timestamp;
                active=true;
            } else if(active && pulse_start_us>0) { // Rising edge: light ends
                int64_t width=e.timestamp-pulse_start_us;
                if(width>=50000 && width<1000000 && n_symbols<sizeof(symbols)-1) {
                    symbols[n_symbols++]=width<DOT_DASH_THRESHOLD_US?'.':'-';
                }
                last_pulse_end_us=e.timestamp;
            }
        }
        if(active && last_level==1 && last_pulse_end_us>0 &&
           esp_timer_get_time()-last_pulse_end_us>=FRAME_DONE_US) finish_frame();
    }
}
