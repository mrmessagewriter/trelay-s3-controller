// Sprinklers1 custom MicroPython board definition.
//
// Hardware:
//   LILYGO T-Relay ESP32-S3
//   ESP32-S3
//   16 MiB flash
//   8 MiB Octal PSRAM
//
// Build with:
//   BOARD=T_RELAY_S3_NCM
//   BOARD_VARIANT=SPIRAM_OCT

#ifndef MICROPY_HW_BOARD_NAME
#define MICROPY_HW_BOARD_NAME "LILYGO T-Relay S3 NCM"
#endif

#define MICROPY_HW_MCU_NAME "ESP32-S3"

// Keep UART REPL available as an additional recovery/debug path.
#define MICROPY_HW_ENABLE_UART_REPL (1)

// Enable USB CDC-NCM networking. This exposes network.USBD_NCM.
#define MICROPY_PY_NETWORK_USBD_NCM (1)

// Friendly USB strings.
#define MICROPY_HW_USB_PRODUCT_FS_STRING "Sprinklers1 Controller"
#define MICROPY_HW_USB_CDC_INTERFACE_STRING "Sprinklers1 Console"
#define MICROPY_PY_NETWORK_USBD_NCM_INTERFACE_STRING "Sprinklers1 USB Network"

// Match ESP32_GENERIC_S3 defaults.
#define MICROPY_HW_I2C0_SCL (9)
#define MICROPY_HW_I2C0_SDA (8)
