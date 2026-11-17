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
    gpio_reset_pin(TX_PIN);
    gpio_set_direction(TX_PIN,GPIO_MODE_OUTPUT);
    gpio_set_level(TX_PIN,0);
    printf("PHASE 4: UART ADDRESS|MESSAGE, A-Z, 0-9, spaces. Send 02|HELLO WORLD\n");
    char line[128], frame[128], out[140];
    while (1) {
        printf("Enter ADDRESS|MESSAGE: "); fflush(stdout);
        if (!fgets(line,sizeof(line),stdin)) { vTaskDelay(pdMS_TO_TICKS(100)); continue; }
        line[strcspn(line,"\r\n")]=0;
        if (strlen(line)<4 || line[2]!='|' ||
            !(line[0]=='0' && (line[1]=='1'||line[1]=='2'))) {
            puts("Invalid command. Use 01|MESSAGE or 02|MESSAGE"); continue;
        }
        char *message=line+3;
        if (!*message || strlen(message)>80) { puts("Message must contain 1-80 characters");continue; }
        int valid=1;
        for (char *p=message;*p;++p) {
            *p=(char)toupper((unsigned char)*p);
            if (!((*p>='A' && *p<='Z') || (*p>='0' && *p<='9') || *p==' ')) valid=0;
        }
        if (!valid) { puts("Unsupported characters: A-Z, 0-9, space only");continue; }
        snprintf(frame,sizeof(frame),"%.2s%s",line,message);
        snprintf(out,sizeof(out),"%s%03u",frame,checksum(frame));
        printf("Transmitting: %s\n",out);
        emit_text(out);
        puts("Frame complete");
    }
}
