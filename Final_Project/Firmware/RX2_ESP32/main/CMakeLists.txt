idf_component_register(
    SRCS "phase8_rx2_file_receiver.c" "phase8_packet_protocol.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_gpio esp_driver_i2c esp_timer
)
