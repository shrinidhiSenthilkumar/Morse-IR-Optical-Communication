# Final implementation

## ESP32 firmware

- `Firmware/TX_ESP32` — infrared Morse transmitter on GPIO17 and file-packet parser.
- `Firmware/RX1_ESP32` — receiver address 01, infrared GPIO16 and SSD1306 OLED.
- `Firmware/RX2_ESP32` — receiver address 02, infrared GPIO16 and SSD1306 OLED.

Each firmware directory is an ESP-IDF project containing `CMakeLists.txt` and `main/` source files. The firmware is unchanged from the verified project package.

## Python applications

In `PC_Applications/`:

```powershell
python Morse_IR_Transmitter_Studio_FINAL.py
python Morse_IR_Receiver_Studio_FINAL.py
python test_final_studios.py
```

Install `pyserial` in the Python environment. Select the appropriate Windows COM ports. Accepted reconstructed text files can be saved on the receiver PC.
