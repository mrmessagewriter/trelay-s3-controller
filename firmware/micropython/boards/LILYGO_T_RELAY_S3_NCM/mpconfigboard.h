// MicroPython custom board definition.
//
// Hardware:
//   LILYGO T-Relay ESP32-S3
//   ESP32-S3
//   16 MiB flash
//   8 MiB Octal PSRAM
//
// Build with:
//   BOARD=LILYGO_T_RELAY_S3_NCM
//   BOARD_VARIANT=SPIRAM_OCT

#ifndef MICROPY_HW_BOARD_NAME
#define MICROPY_HW_BOARD_NAME "LILYGO T-Relay S3 NCM"
#endif

#define MICROPY_HW_MCU_NAME "ESP32-S3"

#define MICROPY_HW_ENABLE_UART_REPL (1)

// The shared TinyUSB descriptor config references this lwIP option.
// ESP-IDF uses Espressif's separate mDNS implementation.
#ifndef LWIP_MDNS_RESPONDER
#define LWIP_MDNS_RESPONDER (0)
#endif

// Expose network.USBD_NCM.
#define MICROPY_PY_NETWORK_USBD_NCM (1)

// DHCP is supplied by ESP-IDF esp_netif, not MicroPython's generic helper.
#define MICROPY_PY_NETWORK_USBD_NCM_DHCP_SERVER (0)

#define MICROPY_HW_USB_PRODUCT_FS_STRING "LILYGO T-Relay S3 MicroPython"
#define MICROPY_HW_USB_CDC_INTERFACE_STRING "MicroPython Console"

/*
 * Do not let an unopened USB CDC console delay application startup.
 *
 * MicroPython's TinyUSB CDC writer waits up to MICROPY_HW_USB_CDC_TX_TIMEOUT
 * whenever the TX FIFO cannot make forward progress.  This controller emits
 * substantial startup diagnostics, while CDC and NCM share the same USB
 * device.  A zero timeout makes console output best-effort/lossy when the host
 * has not opened the serial console, so HTTP/NCM startup never depends on DTR.
 */
#define MICROPY_HW_USB_CDC_TX_TIMEOUT (0)

#define MICROPY_PY_NETWORK_USBD_NCM_INTERFACE_STRING "MicroPython USB Network"

#define MICROPY_HW_I2C0_SCL (9)
#define MICROPY_HW_I2C0_SDA (8)
