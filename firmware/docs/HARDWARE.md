# Hardware

## Target board

LILYGO T-Relay ESP32-S3, six-relay model.

## Flash and PSRAM

The target board used for this project reports:

- 16 MiB flash.
- 8 MiB Octal PSRAM.

Use the MicroPython ESP32-S3 `SPIRAM_OCT` firmware variant so PSRAM is enabled.

## Relay shift register

The relays are driven through a 74HC595 shift register.

Pins:

| Function | GPIO |
| --- | ---: |
| DATA | 7 |
| CLOCK | 5 |
| LATCH | 6 |
| OUTPUT ENABLE | 4 |

Output-enable is active low.

Shift-register bits:

| Bit | Function |
| ---: | --- |
| 0 | Relay 1 |
| 1 | Relay 2 |
| 2 | Relay 3 |
| 3 | Relay 4 |
| 4 | Relay 5 |
| 5 | Relay 6 |
| 6 | Green LED |
| 7 | Red LED |

The firmware performs a relay startup test and leaves all relays off when the
test completes.
