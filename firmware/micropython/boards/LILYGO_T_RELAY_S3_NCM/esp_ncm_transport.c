/*
 * ESP32 USB-NCM transport adapter for MicroPython.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * The RX/TX scheduling model intentionally follows Espressif's
 * esp_tinyusb tinyusb_net.c implementation:
 *
 *   - RX is delivered by tud_network_recv_cb().
 *   - TX requested by the TCP/IP stack is deferred to the TinyUSB task using
 *     usbd_defer_func().
 *   - synchronous TX waits until TinyUSB has accepted/copied the frame.
 *
 * Unlike esp_tinyusb, this file does not install TinyUSB or own descriptors.
 * MicroPython already owns the composite CDC + NCM USB device.
 */

#include <stdlib.h>
#include <string.h>

#include "esp_ncm_transport.h"

#include "freertos/event_groups.h"
#include "freertos/semphr.h"

#include "tusb.h"
#include "device/usbd_pvt.h"

#define ESP_NCM_MAC_LEN (6)
#define ESP_NCM_TX_FINISHED_BIT BIT0

/*
 * MicroPython's descriptor generator reads this symbol when producing the NCM
 * MAC-address string descriptor.
 */
uint8_t tud_network_mac_address[ESP_NCM_MAC_LEN] = {
    0x02, 0x00, 0x00, 0x00, 0x00, 0x01
};

typedef struct _esp_ncm_packet_t {
    void *buffer;
    void *buff_free_arg;
    uint16_t len;
    esp_err_t result;
} esp_ncm_packet_t;

typedef struct _esp_ncm_transport_state_t {
    bool initialized;

    SemaphoreHandle_t buffer_sema;
    EventGroupHandle_t tx_flags;

    esp_ncm_transport_rx_cb_t rx_cb;
    esp_ncm_transport_free_tx_cb_t tx_free_cb;
    esp_ncm_transport_init_cb_t init_cb;

    void *ctx;

    esp_ncm_packet_t *packet_to_send;
} esp_ncm_transport_state_t;

static esp_ncm_transport_state_t s_ncm_transport;

static void esp_ncm_do_send_sync(void *ctx) {
    (void)ctx;

    if (
        xSemaphoreTake(
            s_ncm_transport.buffer_sema,
            0
        ) != pdTRUE
        || s_ncm_transport.packet_to_send == NULL
    ) {
        return;
    }

    esp_ncm_packet_t *packet =
        s_ncm_transport.packet_to_send;

    if (tud_network_can_xmit(packet->len)) {
        /*
         * The ref passed to tud_network_xmit() is the packet wrapper, matching
         * Espressif's tinyusb_net.c. tud_network_xmit_cb() then copies the
         * actual Ethernet frame into TinyUSB's NCM transmit buffer.
         */
        tud_network_xmit(
            packet,
            packet->len
        );

        packet->result = ESP_OK;
    } else {
        packet->result = ESP_FAIL;
    }

    xSemaphoreGive(
        s_ncm_transport.buffer_sema
    );

    xEventGroupSetBits(
        s_ncm_transport.tx_flags,
        ESP_NCM_TX_FINISHED_BIT
    );
}

esp_err_t esp_ncm_transport_send_sync(
    void *buffer,
    uint16_t len,
    void *buff_free_arg,
    TickType_t timeout
) {
    if (!s_ncm_transport.initialized) {
        return ESP_ERR_INVALID_STATE;
    }

    /*
     * Espressif's current NCM transport uses mounted state here rather than
     * tud_ready(). This allows the first DHCP/ARP replies immediately after
     * enumeration.
     */
    if (!tud_mounted()) {
        return ESP_ERR_INVALID_STATE;
    }

    if (buffer == NULL || len == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    /*
     * Lazily allocate synchronization objects, as Espressif does.
     */
    if (s_ncm_transport.tx_flags == NULL) {
        s_ncm_transport.tx_flags =
            xEventGroupCreate();

        if (s_ncm_transport.tx_flags == NULL) {
            return ESP_ERR_NO_MEM;
        }
    }

    if (s_ncm_transport.buffer_sema == NULL) {
        s_ncm_transport.buffer_sema =
            xSemaphoreCreateBinary();

        if (s_ncm_transport.buffer_sema == NULL) {
            return ESP_ERR_NO_MEM;
        }
    }

    esp_ncm_packet_t packet = {
        .buffer = buffer,
        .buff_free_arg = buff_free_arg,
        .len = len,
        .result = ESP_FAIL,
    };

    s_ncm_transport.packet_to_send = &packet;

    /*
     * Mark the packet available to the deferred TinyUSB task callback.
     */
    xSemaphoreGive(
        s_ncm_transport.buffer_sema
    );

    /*
     * This is the critical difference from the previous implementation:
     * TinyUSB network TX is executed in the TinyUSB task, not directly from
     * the lwIP/esp_netif transmit callback.
     */
    usbd_defer_func(
        esp_ncm_do_send_sync,
        NULL,
        false
    );

    EventBits_t bits =
        xEventGroupWaitBits(
            s_ncm_transport.tx_flags,
            ESP_NCM_TX_FINISHED_BIT,
            pdTRUE,
            pdTRUE,
            timeout
        );

    /*
     * Wait until the TinyUSB task is no longer accessing the stack-local
     * packet wrapper before invalidating it.
     */
    xSemaphoreTake(
        s_ncm_transport.buffer_sema,
        portMAX_DELAY
    );

    s_ncm_transport.packet_to_send = NULL;

    if (bits & ESP_NCM_TX_FINISHED_BIT) {
        return packet.result;
    }

    return ESP_ERR_TIMEOUT;
}

esp_err_t esp_ncm_transport_init(
    const esp_ncm_transport_config_t *cfg
) {
    if (cfg == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_ncm_transport.initialized) {
        return ESP_ERR_INVALID_STATE;
    }

    memset(
        &s_ncm_transport,
        0,
        sizeof(s_ncm_transport)
    );

    s_ncm_transport.rx_cb =
        cfg->on_recv_callback;

    s_ncm_transport.tx_free_cb =
        cfg->free_tx_buffer;

    s_ncm_transport.init_cb =
        cfg->on_init_callback;

    s_ncm_transport.ctx =
        cfg->user_context;

    memcpy(
        tud_network_mac_address,
        cfg->mac_addr,
        ESP_NCM_MAC_LEN
    );

    s_ncm_transport.initialized = true;

    return ESP_OK;
}

bool esp_ncm_transport_mounted(void) {
    return (
        s_ncm_transport.initialized
        && tud_mounted()
    );
}

/* ------------------------------------------------------------------------- */
/* TinyUSB NCM callbacks                                                     */
/* ------------------------------------------------------------------------- */

bool tud_network_recv_cb(
    const uint8_t *src,
    uint16_t size
) {
    if (s_ncm_transport.rx_cb != NULL) {
        s_ncm_transport.rx_cb(
            (void *)src,
            size,
            s_ncm_transport.ctx
        );
    }

    /*
     * Match Espressif's transport behavior: renew after the user RX callback
     * returns.
     */
    tud_network_recv_renew();

    return true;
}

uint16_t tud_network_xmit_cb(
    uint8_t *dst,
    void *ref,
    uint16_t arg
) {
    esp_ncm_packet_t *packet =
        (esp_ncm_packet_t *)ref;

    if (
        dst == NULL
        || packet == NULL
        || packet->buffer == NULL
    ) {
        return 0;
    }

    uint16_t len = arg;

    if (len > packet->len) {
        len = packet->len;
    }

    memcpy(
        dst,
        packet->buffer,
        len
    );

    if (s_ncm_transport.tx_free_cb != NULL) {
        s_ncm_transport.tx_free_cb(
            packet->buff_free_arg,
            s_ncm_transport.ctx
        );
    }

    return len;
}

void tud_network_init_cb(void) {
    if (s_ncm_transport.init_cb != NULL) {
        s_ncm_transport.init_cb(
            s_ncm_transport.ctx
        );
    }
}
