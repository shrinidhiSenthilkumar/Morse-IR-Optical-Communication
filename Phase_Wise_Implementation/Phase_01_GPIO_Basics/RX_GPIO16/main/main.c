/* Reconstructed Phase 1 lab: GPIO16 IR phototransistor input test.
 * Flash ONLY to a receiver ESP32. Use external 10k pull-up to 3.3V.
 * Expected: LED off -> GPIO16 idle HIGH; IR illuminated -> LOW
 * for the active-low phototransistor interface used in the final project.
 * Never apply 5V to GPIO16.
 */
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#define RX_PIN GPIO_NUM_16
void app_main(void) {
    gpio_config_t config = {0};
    config.pin_bit_mask = 1ULL << RX_PIN;
    config.mode = GPIO_MODE_INPUT;
    config.pull_up_en = GPIO_PULLUP_ENABLE;
    config.intr_type = GPIO_INTR_DISABLE;
    ESP_ERROR_CHECK(gpio_config(&config));
    printf("PHASE 1: GPIO16 IR input test\n");
    int prior = -1;
    while (1) {
        int level = gpio_get_level(RX_PIN);
        if (level != prior) {
            printf("GPIO16 level = %d (%s)\n", level, level == 0 ? "IR detected" : "idle/no IR");
            prior = level;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
