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

// Keep UART REPL available as an additional recovery/debug path.
#define MICROPY_HW_ENABLE_UART_REPL (1)

// ESP-IDF does not use lwIP's built-in mDNS responder.  It provides its
// own separate espressif/mdns component instead.
//
// MicroPython's TinyUSB NCM configuration uses LWIP_MDNS_RESPONDER to size
// its transfer buffers and network_usbd_ncm.c uses it to conditionally call
// lwIP's mdns_resp_* API.  Define it as disabled for the ESP-IDF port.
#ifndef LWIP_MDNS_RESPONDER
#define LWIP_MDNS_RESPONDER (0)
#endif

// Enable USB CDC-NCM networking. This exposes network.USBD_NCM.
#define MICROPY_PY_NETWORK_USBD_NCM (1)

// Run MicroPython's small DHCP server on the USB network interface so the
// connected host receives an address automatically.
#define MICROPY_PY_NETWORK_USBD_NCM_DHCP_SERVER (1)

// Friendly USB strings for the MicroPython runtime.
#define MICROPY_HW_USB_PRODUCT_FS_STRING "LILYGO T-Relay S3 MicroPython"
#define MICROPY_HW_USB_CDC_INTERFACE_STRING "MicroPython Console"
#define MICROPY_PY_NETWORK_USBD_NCM_INTERFACE_STRING "MicroPython USB Network"

// Match ESP32_GENERIC_S3 defaults.
#define MICROPY_HW_I2C0_SCL (9)
#define MICROPY_HW_I2C0_SDA (8)
