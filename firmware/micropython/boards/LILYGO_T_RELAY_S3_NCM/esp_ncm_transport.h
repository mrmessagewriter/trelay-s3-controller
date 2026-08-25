/*
 * ESP32 USB-NCM transport adapter for MicroPython.
 *
 * The transport flow is based on Espressif's esp_tinyusb tinyusb_net layer,
 * but USB driver installation and descriptors remain owned by MicroPython.
 */

#ifndef MICROPY_INCLUDED_ESP32_NCM_TRANSPORT_H
#define MICROPY_INCLUDED_ESP32_NCM_TRANSPORT_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"

typedef esp_err_t (*esp_ncm_transport_rx_cb_t)(
    void *buffer,
    uint16_t len,
    void *ctx
);

typedef void (*esp_ncm_transport_free_tx_cb_t)(
    void *buffer,
    void *ctx
);

typedef void (*esp_ncm_transport_init_cb_t)(
    void *ctx
);

typedef struct _esp_ncm_transport_config_t {
    uint8_t mac_addr[6];
    esp_ncm_transport_rx_cb_t on_recv_callback;
    esp_ncm_transport_free_tx_cb_t free_tx_buffer;
    esp_ncm_transport_init_cb_t on_init_callback;
    void *user_context;
} esp_ncm_transport_config_t;

esp_err_t esp_ncm_transport_init(
    const esp_ncm_transport_config_t *cfg
);

esp_err_t esp_ncm_transport_send_sync(
    void *buffer,
    uint16_t len,
    void *buff_free_arg,
    TickType_t timeout
);

bool esp_ncm_transport_mounted(void);

#endif
