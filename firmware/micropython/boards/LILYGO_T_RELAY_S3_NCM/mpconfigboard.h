// MicroPython board definition for the LILYGO T-Relay ESP32-S3.
// 16 MiB flash, 8 MiB Octal PSRAM, USB CDC console + upstream CDC-NCM.
#ifndef MICROPY_HW_BOARD_NAME
#define MICROPY_HW_BOARD_NAME "LILYGO T-Relay S3 NCM"
#endif
#define MICROPY_HW_MCU_NAME "ESP32-S3"
#define MICROPY_HW_ENABLE_UART_REPL (1)

// shared/tinyusb/mp_usbd_descriptor.c references this lwIP option.
#ifndef LWIP_MDNS_RESPONDER
#define LWIP_MDNS_RESPONDER (0)
#endif

// Use MicroPython master's upstream network.USBD_NCM implementation.
#define MICROPY_PY_NETWORK_USBD_NCM (1)
#define MICROPY_PY_NETWORK_USBD_NCM_DHCP_SERVER (1)

#define MICROPY_HW_USB_PRODUCT_FS_STRING "LILYGO T-Relay S3 MicroPython"
#define MICROPY_HW_USB_CDC_INTERFACE_STRING "MicroPython Console"
#define MICROPY_PY_NETWORK_USBD_NCM_INTERFACE_STRING "MicroPython USB Network"

// Do not let an unopened CDC console block application/NCM startup.
#define MICROPY_HW_USB_CDC_TX_TIMEOUT (0)

#define MICROPY_HW_I2C0_SCL (9)
#define MICROPY_HW_I2C0_SDA (8)
