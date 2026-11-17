# Morse-Based IR Optical Communication System

Embedded optical communication using three ESP32 microcontrollers: one infrared transmitter and two independently addressed receivers.

## System

- Transmitter: ESP32 GPIO17, IR LED, UART input and Morse-code pulse generation.
- Receivers: ESP32 GPIO16, phototransistor sensing, GPIO interrupts, FreeRTOS event processing and SSD1306 OLED displays over I2C.
- Receiver addresses: `01` (RX1) and `02` (RX2).
- Communication: Morse encoding/decoding, address verification, additive checksum and numbered-packet text transfer.
- PC applications: Python transmitter and receiver GUIs.

## Repository layout

| Folder | Description |
| --- | --- |
| `Phase_Wise_Implementation` | Phase 1–9 code and individual development tests |
| `Final_Project/Firmware` | Final ESP-IDF transmitter, RX1 and RX2 projects |
| `Final_Project/PC_Applications` | Final transmitter and receiver GUIs and Python tests |
| `Tests_and_Evidence` | Original hardware photographs, serial/GUI output screenshots and image index |

**Phase source note:** Phase 1–5 contain recreated reference test programs requiring hardware verification; these are not original dated source snapshots. Phase 6–9 contain project development artifacts retained from the existing source package. The final firmware and GUI source files are kept unchanged.

## Run the final PC applications

From `Final_Project/PC_Applications` on Windows:

```powershell
python -m pip install pyserial
python Morse_IR_Transmitter_Studio_FINAL.py
python Morse_IR_Receiver_Studio_FINAL.py
```

Use the COM ports currently assigned to the transmitter and receivers. The ESP32 firmware projects are located under `Final_Project/Firmware` and use ESP-IDF.

## File transfer

Longer text is transmitted as numbered packets with payloads of up to 40 characters. The receiver reconstructs accepted packets; the PC receiver application can save verified reconstructed text. This is a one-way optical link without receiver-to-transmitter acknowledgements.
