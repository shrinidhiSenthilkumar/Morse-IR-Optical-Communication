/* Reconstructed staged Morse TX demonstration. NOT a preserved historical commit.
 * ESP-IDF; GPIO17 drives the IR transmitter's driver circuit.
 * Active HIGH on TX, receiver hardware sees active LOW at GPIO16.
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <ctype.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#define TX_PIN GPIO_NUM_17
#define DOT_MS 200
#define DASH_MS 600
#define SYMBOL_GAP_MS 200
#define LETTER_GAP_MS 700
#define WORD_EXTRA_MS 1400
static const char *morse_table[36] = {
    ".-","-...","-.-.","-..",".","..-.","--.","....","..",".---","-.-",".-..","--","-.","---",
    ".--.","--.-",".-.","...","-","..-","...-",".--","-..-","-.--","--..",
    "-----",".----","..---","...--","....-",".....","-....","--...","---..","----."
};
static const char characters[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

static const char* morse_for(char ch) {
    for (int i=0;i<36;++i) if (characters[i] == ch) return morse_table[i];
    return NULL;
}
static void pulse(int ms) {
    gpio_set_level(TX_PIN,1);
    vTaskDelay(pdMS_TO_TICKS(ms));
    gpio_set_level(TX_PIN,0);
}
static void emit_text(const char *p) {
    for (; *p; ++p) {
        if (*p == ' ') { vTaskDelay(pdMS_TO_TICKS(WORD_EXTRA_MS)); continue; }
        const char* pattern = morse_for(*p);
        if (!pattern) { printf("Unsupported: %c\n", *p); continue; }
        for (const char* m=pattern;*m;++m) {
            pulse(*m == '.' ? DOT_MS : DASH_MS);
            vTaskDelay(pdMS_TO_TICKS(SYMBOL_GAP_MS));
        }
        vTaskDelay(pdMS_TO_TICKS(LETTER_GAP_MS));
    }
}
static unsigned checksum(const char *frame) {
    unsigned sum=0;
    while (*frame) sum+=(unsigned char)*frame++;
    return sum&255u;
}
void app_main(void) {
    gpio_reset_pin(TX_PIN);gpio_set_direction(TX_PIN,GPIO_MODE_OUTPUT);gpio_set_level(TX_PIN,0);
    printf("PHASE 5: NEGATIVE CHECKSUM TEST; correct 02SOS087; transmitting 02SOS099\n");
    while(1) { emit_text("02SOS099"); puts("Wrong-checksum frame sent; RX2 must reject");vTaskDelay(pdMS_TO_TICKS(3000)); }
}
