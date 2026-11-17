/* Reconstructed Phase 1 lab: verify GPIO17 IR transmitter switching.
 * Flash ONLY to the transmitter ESP32. GPIO17 drives an IR LED driver.
 * No receiver, checksum or Morse framing is needed for this first test.
 */
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#define TX_PIN GPIO_NUM_17
void app_main(void) {
    gpio_reset_pin(TX_PIN);
    gpio_set_direction(TX_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(TX_PIN, 0);
    printf("PHASE 1: GPIO17 output test; pulses every 1 second.\n");
    while (1) {
        gpio_set_level(TX_PIN, 1);
        printf("GPIO17 = HIGH (IR ON)\n");
        vTaskDelay(pdMS_TO_TICKS(1000));
        gpio_set_level(TX_PIN, 0);
        printf("GPIO17 = LOW  (IR OFF)\n");
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
