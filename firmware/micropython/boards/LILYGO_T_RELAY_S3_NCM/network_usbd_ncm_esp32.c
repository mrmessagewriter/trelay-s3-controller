/*
 * ESP32-native MicroPython USB CDC-NCM backend for LILYGO_T_RELAY_S3_NCM.
 *
 * USB device/class transport:
 *   MicroPython TinyUSB composite CDC + NCM device
 *
 * NCM RX/TX scheduling:
 *   Espressif-style deferred TinyUSB network transport
 *
 * TCP/IP integration:
 *   ESP-IDF esp_netif + lwIP
 *
 * USB subnet:
 *   ESP32:   192.168.7.1/24
 *   Windows: DHCP-assigned 192.168.7.x
 *   Gateway: none
 */

#include <string.h>

#include "py/runtime.h"
#include "py/mperrno.h"

#if MICROPY_PY_NETWORK_USBD_NCM

#include "extmod/network_usbd_ncm.h"

#include "esp_err.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_netif_defaults.h"

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"

#include "tusb.h"
#include "device/usbd_pvt.h"


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


#include "shared/netutils/netutils.h"

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


const mp_obj_type_t mod_network_nic_type_ncm;

#define USB_NCM_IP_A (192)
#define USB_NCM_IP_B (168)
#define USB_NCM_IP_C (7)
#define USB_NCM_IP_D (1)

typedef struct _ncm_obj_t {
    mp_obj_base_t base;

    esp_netif_t *netif;

    bool init;
    bool enabled;
    bool stack_started;

    uint8_t mac[6];

    uint32_t rx_frames;
    uint32_t rx_bytes;
    uint32_t rx_errors;

    uint32_t tx_frames;
    uint32_t tx_bytes;
    uint32_t tx_errors;

    uint32_t rx_arp;
    uint32_t tx_arp;
    uint32_t rx_ipv4;
    uint32_t tx_ipv4;
    uint32_t rx_icmp;
    uint32_t tx_icmp;
    uint32_t rx_tcp;
    uint32_t tx_tcp;
    uint32_t rx_udp;
    uint32_t tx_udp;

    uint32_t last_rx_len;
    uint32_t last_tx_len;

    uint32_t last_rx_ethertype;
    uint32_t last_tx_ethertype;

    uint32_t last_rx_ip_proto;
    uint32_t last_tx_ip_proto;

    uint32_t last_rx_tcp_src_port;
    uint32_t last_rx_tcp_dst_port;
    uint32_t last_rx_tcp_flags;

    uint32_t last_tx_tcp_src_port;
    uint32_t last_tx_tcp_dst_port;
    uint32_t last_tx_tcp_flags;
} ncm_obj_t;

static ncm_obj_t ncm_obj;
static esp_netif_ip_info_t ncm_ip_info;

static void ncm_raise_esp_error(
    esp_err_t err
) {
    if (err == ESP_OK) {
        return;
    }

    if (err == ESP_ERR_NO_MEM) {
        mp_raise_OSError(MP_ENOMEM);
    }

    if (err == ESP_ERR_INVALID_ARG) {
        mp_raise_ValueError(
            MP_ERROR_TEXT("invalid argument")
        );
    }

    mp_raise_msg_varg(
        &mp_type_OSError,
        MP_ERROR_TEXT("ESP-NETIF error 0x%x"),
        (unsigned int)err
    );
}

/*
 * The receive buffer is owned by TinyUSB. esp_netif_receive() consumes/copies
 * the Ethernet frame synchronously before tud_network_recv_renew() allows the
 * NCM class to reuse it, so there is nothing for esp_netif to free here.
 */
static void ncm_free_rx_buffer(
    void *buffer,
    void *ctx
) {
    (void)buffer;
    (void)ctx;
}


static uint16_t ncm_read_be16(
    const uint8_t *p
) {
    return (uint16_t)(
        ((uint16_t)p[0] << 8)
        | p[1]
    );
}

static void ncm_record_frame(
    ncm_obj_t *self,
    const void *buffer,
    size_t len,
    bool tx
) {
    if (
        self == NULL
        || buffer == NULL
        || len < 14
    ) {
        return;
    }

    const uint8_t *frame =
        (const uint8_t *)buffer;

    uint16_t ethertype =
        ncm_read_be16(
            frame + 12
        );

    if (tx) {
        self->last_tx_len =
            (uint32_t)len;

        self->last_tx_ethertype =
            ethertype;
    } else {
        self->last_rx_len =
            (uint32_t)len;

        self->last_rx_ethertype =
            ethertype;
    }

    if (ethertype == 0x0806) {
        if (tx) {
            self->tx_arp += 1;
        } else {
            self->rx_arp += 1;
        }

        return;
    }

    if (
        ethertype != 0x0800
        || len < 34
    ) {
        return;
    }

    if (tx) {
        self->tx_ipv4 += 1;
    } else {
        self->rx_ipv4 += 1;
    }

    size_t ip_offset = 14;

    uint8_t version_ihl =
        frame[ip_offset];

    if ((version_ihl >> 4) != 4) {
        return;
    }

    size_t ihl =
        (size_t)(
            version_ihl & 0x0f
        ) * 4;

    if (
        ihl < 20
        || len < ip_offset + ihl
    ) {
        return;
    }

    uint8_t proto =
        frame[ip_offset + 9];

    if (tx) {
        self->last_tx_ip_proto =
            proto;
    } else {
        self->last_rx_ip_proto =
            proto;
    }

    if (proto == 1) {
        if (tx) {
            self->tx_icmp += 1;
        } else {
            self->rx_icmp += 1;
        }

        return;
    }

    if (proto == 17) {
        if (tx) {
            self->tx_udp += 1;
        } else {
            self->rx_udp += 1;
        }

        return;
    }

    if (proto != 6) {
        return;
    }

    if (tx) {
        self->tx_tcp += 1;
    } else {
        self->rx_tcp += 1;
    }

    size_t tcp_offset =
        ip_offset + ihl;

    if (len < tcp_offset + 14) {
        return;
    }

    uint16_t src_port =
        ncm_read_be16(
            frame + tcp_offset
        );

    uint16_t dst_port =
        ncm_read_be16(
            frame + tcp_offset + 2
        );

    uint8_t flags =
        frame[tcp_offset + 13];

    if (tx) {
        self->last_tx_tcp_src_port =
            src_port;

        self->last_tx_tcp_dst_port =
            dst_port;

        self->last_tx_tcp_flags =
            flags;
    } else {
        self->last_rx_tcp_src_port =
            src_port;

        self->last_rx_tcp_dst_port =
            dst_port;

        self->last_rx_tcp_flags =
            flags;
    }
}

/*
 * USB -> ESP-IDF network stack.
 *
 * This is intentionally the same handoff used by Espressif examples that
 * connect a custom Ethernet-like driver to esp_netif.
 */
static esp_err_t ncm_transport_rx(
    void *buffer,
    uint16_t len,
    void *ctx
) {
    ncm_obj_t *self =
        (ncm_obj_t *)ctx;

    if (
        self == NULL
        || self->netif == NULL
        || !self->enabled
    ) {
        return ESP_ERR_INVALID_STATE;
    }

    self->rx_frames += 1;
    self->rx_bytes += len;

    ncm_record_frame(
        self,
        buffer,
        len,
        false
    );

    esp_err_t err =
        esp_netif_receive(
            self->netif,
            buffer,
            len,
            NULL
        );

    if (err != ESP_OK) {
        self->rx_errors += 1;
    }

    return err;
}

/*
 * ESP-IDF/lwIP -> USB.
 *
 * Do not call tud_network_xmit() directly here. Espressif's NCM layer defers
 * the actual TinyUSB send into the USB task and waits synchronously until
 * TinyUSB has copied/accepted the frame.
 */
static esp_err_t ncm_driver_transmit(
    void *handle,
    void *buffer,
    size_t len
) {
    ncm_obj_t *self =
        (ncm_obj_t *)handle;

    if (
        self == NULL
        || !self->enabled
        || !self->stack_started
    ) {
        return ESP_ERR_INVALID_STATE;
    }

    if (
        buffer == NULL
        || len == 0
        || len > UINT16_MAX
    ) {
        return ESP_ERR_INVALID_ARG;
    }

    self->tx_frames += 1;
    self->tx_bytes += (uint32_t)len;

    ncm_record_frame(
        self,
        buffer,
        len,
        true
    );

    esp_err_t err =
        esp_ncm_transport_send_sync(
            buffer,
            (uint16_t)len,
            NULL,
            portMAX_DELAY
        );

    if (err != ESP_OK) {
        self->tx_errors += 1;
    }

    return err;
}

static void ncm_start_stack(
    ncm_obj_t *self
) {
    if (
        self == NULL
        || !self->init
        || !self->enabled
        || self->netif == NULL
        || self->stack_started
    ) {
        return;
    }

    ncm_raise_esp_error(
        esp_netif_set_ip_info(
            self->netif,
            &ncm_ip_info
        )
    );

    /*
     * Match the ordering in Espressif's custom-USB esp_netif examples:
     * start the interface first, then mark the Ethernet link connected.
     */
    esp_netif_action_start(
        self->netif,
        NULL,
        0,
        NULL
    );

    esp_netif_action_connected(
        self->netif,
        NULL,
        0,
        NULL
    );

    esp_err_t dhcp_err =
        esp_netif_dhcps_start(
            self->netif
        );

    if (
        dhcp_err != ESP_OK
        && dhcp_err
            != ESP_ERR_ESP_NETIF_DHCP_ALREADY_STARTED
    ) {
        ncm_raise_esp_error(
            dhcp_err
        );
    }

    self->stack_started = true;
}

static void ncm_stop_stack(
    ncm_obj_t *self
) {
    if (
        self == NULL
        || !self->init
        || self->netif == NULL
        || !self->stack_started
    ) {
        return;
    }

    esp_err_t dhcp_err =
        esp_netif_dhcps_stop(
            self->netif
        );

    if (
        dhcp_err != ESP_OK
        && dhcp_err
            != ESP_ERR_ESP_NETIF_DHCP_ALREADY_STOPPED
    ) {
        ncm_raise_esp_error(
            dhcp_err
        );
    }

    esp_netif_action_disconnected(
        self->netif,
        NULL,
        0,
        NULL
    );

    esp_netif_action_stop(
        self->netif,
        NULL,
        0,
        NULL
    );

    self->stack_started = false;
}

/*
 * TinyUSB calls this when the NCM class is initialized by the host.
 *
 * This is also how Espressif's own NCM examples synchronize the USB class
 * with the network interface lifecycle.
 */
static void ncm_transport_initialized(
    void *ctx
) {
    ncm_obj_t *self =
        (ncm_obj_t *)ctx;

    ncm_start_stack(
        self
    );
}

static void ncm_init(void) {
    if (ncm_obj.init) {
        return;
    }

    memset(
        &ncm_obj,
        0,
        sizeof(ncm_obj)
    );

    ncm_obj.base.type =
        (mp_obj_type_t *)&mod_network_nic_type_ncm;

    ncm_raise_esp_error(
        esp_netif_init()
    );

    if (
        esp_read_mac(
            ncm_obj.mac,
            ESP_MAC_ETH
        ) != ESP_OK
    ) {
        mp_raise_OSError(
            MP_EIO
        );
    }

    /*
     * Turn the hardware-derived MAC into a locally administered unicast
     * address for the virtual USB Ethernet interface.
     */
    ncm_obj.mac[0] &= 0xfe;
    ncm_obj.mac[0] |= 0x02;

    esp_netif_set_ip4_addr(
        &ncm_ip_info.ip,
        USB_NCM_IP_A,
        USB_NCM_IP_B,
        USB_NCM_IP_C,
        USB_NCM_IP_D
    );

    esp_netif_set_ip4_addr(
        &ncm_ip_info.netmask,
        255,
        255,
        255,
        0
    );

    /*
     * No gateway is advertised for the controller USB link.
     */
    esp_netif_set_ip4_addr(
        &ncm_ip_info.gw,
        0,
        0,
        0,
        0
    );

    static esp_netif_inherent_config_t base_cfg = {
        .flags = (esp_netif_flags_t)(
            ESP_NETIF_DHCP_SERVER
            | ESP_NETIF_FLAG_AUTOUP
        ),

        .ip_info = &ncm_ip_info,

        .get_ip_event = 0,
        .lost_ip_event = 0,

        .if_key = "USB_NCM",
        .if_desc = "usb_ncm",

        .route_prio = 10,

        .bridge_info = NULL,
    };

    static esp_netif_driver_ifconfig_t driver_cfg = {
        .handle =
            (esp_netif_iodriver_handle)&ncm_obj,

        .transmit =
            ncm_driver_transmit,

        .transmit_wrap =
            NULL,

        .driver_free_rx_buffer =
            ncm_free_rx_buffer,

        .driver_set_mac_filter =
            NULL,
    };

    esp_netif_config_t cfg = {
        .base =
            &base_cfg,

        .driver =
            &driver_cfg,

        .stack =
            ESP_NETIF_NETSTACK_DEFAULT_ETH,
    };

    ncm_obj.netif =
        esp_netif_new(
            &cfg
        );

    if (ncm_obj.netif == NULL) {
        mp_raise_OSError(
            MP_ENOMEM
        );
    }

    ncm_raise_esp_error(
        esp_netif_set_mac(
            ncm_obj.netif,
            ncm_obj.mac
        )
    );

    /*
     * Install only the NCM class transport. MicroPython has already installed
     * and owns TinyUSB itself, including the CDC console and descriptors.
     */
    esp_ncm_transport_config_t transport_cfg = {
        .on_recv_callback =
            ncm_transport_rx,

        .free_tx_buffer =
            NULL,

        .on_init_callback =
            ncm_transport_initialized,

        .user_context =
            &ncm_obj,
    };

    memcpy(
        transport_cfg.mac_addr,
        ncm_obj.mac,
        sizeof(transport_cfg.mac_addr)
    );

    esp_err_t transport_err =
        esp_ncm_transport_init(
            &transport_cfg
        );

    if (
        transport_err != ESP_OK
        && transport_err != ESP_ERR_INVALID_STATE
    ) {
        ncm_raise_esp_error(
            transport_err
        );
    }

    ncm_obj.init = true;
    ncm_obj.enabled = true;

    /*
     * ncm_auto_init() normally runs before USB enumeration. On a soft reset,
     * however, the USB device may already be mounted, so restore the stack
     * immediately in that case.
     */
    if (esp_ncm_transport_mounted()) {
        ncm_start_stack(
            &ncm_obj
        );
    }
}

/*
 * Called by mod_network_init() before USB enumeration.
 */
void ncm_auto_init(void) {
    if (!ncm_obj.init) {
        ncm_init();
        return;
    }

    ncm_obj.enabled = true;

    if (
        esp_ncm_transport_mounted()
        && !ncm_obj.stack_started
    ) {
        ncm_start_stack(
            &ncm_obj
        );
    }
}

/******************************************************************************/
/* MicroPython bindings */

static mp_obj_t ncm_make_new(
    const mp_obj_type_t *type,
    size_t n_args,
    size_t n_kw,
    const mp_obj_t *args
) {
    (void)type;
    (void)args;

    mp_arg_check_num(
        n_args,
        n_kw,
        0,
        0,
        false
    );

    if (!ncm_obj.init) {
        ncm_init();
    }

    return MP_OBJ_FROM_PTR(
        &ncm_obj
    );
}

static mp_obj_t ncm_status(
    mp_obj_t self_in
) {
    ncm_obj_t *self =
        MP_OBJ_TO_PTR(
            self_in
        );

    return MP_OBJ_NEW_SMALL_INT(
        self->enabled
        && self->stack_started
        && self->netif != NULL
        && esp_netif_is_netif_up(
            self->netif
        )
    );
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    ncm_status_obj,
    ncm_status
);

static mp_obj_t ncm_isconnected(
    mp_obj_t self_in
) {
    ncm_obj_t *self =
        MP_OBJ_TO_PTR(
            self_in
        );

    return mp_obj_new_bool(
        self->enabled
        && self->stack_started
        && esp_ncm_transport_mounted()
    );
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    ncm_isconnected_obj,
    ncm_isconnected
);

static mp_obj_t ncm_active(
    size_t n_args,
    const mp_obj_t *args
) {
    ncm_obj_t *self =
        MP_OBJ_TO_PTR(
            args[0]
        );

    if (n_args == 1) {
        return mp_obj_new_bool(
            self->enabled
        );
    }

    bool enable =
        mp_obj_is_true(
            args[1]
        );

    self->enabled =
        enable;

    if (enable) {
        if (
            esp_ncm_transport_mounted()
            && !self->stack_started
        ) {
            ncm_start_stack(
                self
            );
        }
    } else {
        ncm_stop_stack(
            self
        );
    }

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(
    ncm_active_obj,
    1,
    2,
    ncm_active
);

static mp_obj_t ncm_ifconfig(
    size_t n_args,
    const mp_obj_t *args
) {
    ncm_obj_t *self =
        MP_OBJ_TO_PTR(
            args[0]
        );

    if (self->netif == NULL) {
        mp_raise_OSError(
            MP_ENODEV
        );
    }

    esp_netif_ip_info_t info;
    esp_netif_dns_info_t dns;

    ncm_raise_esp_error(
        esp_netif_get_ip_info(
            self->netif,
            &info
        )
    );

    memset(
        &dns,
        0,
        sizeof(dns)
    );

    esp_netif_get_dns_info(
        self->netif,
        ESP_NETIF_DNS_MAIN,
        &dns
    );

    if (n_args == 1) {
        mp_obj_t tuple[4] = {
            netutils_format_ipv4_addr(
                (uint8_t *)&info.ip,
                NETUTILS_BIG
            ),

            netutils_format_ipv4_addr(
                (uint8_t *)&info.netmask,
                NETUTILS_BIG
            ),

            netutils_format_ipv4_addr(
                (uint8_t *)&info.gw,
                NETUTILS_BIG
            ),

            netutils_format_ipv4_addr(
                (uint8_t *)&dns.ip.u_addr.ip4,
                NETUTILS_BIG
            ),
        };

        return mp_obj_new_tuple(
            4,
            tuple
        );
    }

    if (
        !mp_obj_is_type(
            args[1],
            &mp_type_tuple
        )
        && !mp_obj_is_type(
            args[1],
            &mp_type_list
        )
    ) {
        mp_raise_ValueError(
            MP_ERROR_TEXT("invalid arguments")
        );
    }

    mp_obj_t *items;

    mp_obj_get_array_fixed_n(
        args[1],
        4,
        &items
    );

    esp_netif_ip_info_t new_info;

    netutils_parse_ipv4_addr(
        items[0],
        (uint8_t *)&new_info.ip,
        NETUTILS_BIG
    );

    netutils_parse_ipv4_addr(
        items[1],
        (uint8_t *)&new_info.netmask,
        NETUTILS_BIG
    );

    netutils_parse_ipv4_addr(
        items[2],
        (uint8_t *)&new_info.gw,
        NETUTILS_BIG
    );

    bool was_started =
        self->stack_started;

    if (was_started) {
        ncm_stop_stack(
            self
        );
    }

    ncm_ip_info =
        new_info;

    ncm_raise_esp_error(
        esp_netif_set_ip_info(
            self->netif,
            &ncm_ip_info
        )
    );

    if (
        was_started
        && self->enabled
    ) {
        ncm_start_stack(
            self
        );
    }

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(
    ncm_ifconfig_obj,
    1,
    2,
    ncm_ifconfig
);

static mp_obj_t ncm_ipconfig(
    size_t n_args,
    const mp_obj_t *args,
    mp_map_t *kwargs
) {
    ncm_obj_t *self =
        MP_OBJ_TO_PTR(
            args[0]
        );

    if (self->netif == NULL) {
        mp_raise_OSError(
            MP_ENODEV
        );
    }

    if (kwargs->used != 0) {
        mp_raise_ValueError(
            MP_ERROR_TEXT(
                "setting ipconfig is not supported"
            )
        );
    }

    if (n_args != 2) {
        mp_raise_TypeError(
            MP_ERROR_TEXT(
                "must query one param"
            )
        );
    }

    qstr key =
        mp_obj_str_get_qstr(
            args[1]
        );

    esp_netif_ip_info_t info;

    ncm_raise_esp_error(
        esp_netif_get_ip_info(
            self->netif,
            &info
        )
    );

    if (key == MP_QSTR_addr4) {
        mp_obj_t tuple[2] = {
            netutils_format_ipv4_addr(
                (uint8_t *)&info.ip,
                NETUTILS_BIG
            ),

            MP_OBJ_NEW_SMALL_INT(
                24
            ),
        };

        return mp_obj_new_tuple(
            2,
            tuple
        );
    }

    if (key == MP_QSTR_gw4) {
        return netutils_format_ipv4_addr(
            (uint8_t *)&info.gw,
            NETUTILS_BIG
        );
    }

    if (key == MP_QSTR_dns) {
        esp_netif_dns_info_t dns;

        memset(
            &dns,
            0,
            sizeof(dns)
        );

        ncm_raise_esp_error(
            esp_netif_get_dns_info(
                self->netif,
                ESP_NETIF_DNS_MAIN,
                &dns
            )
        );

        return netutils_format_ipv4_addr(
            (uint8_t *)&dns.ip.u_addr.ip4,
            NETUTILS_BIG
        );
    }

    mp_raise_ValueError(
        MP_ERROR_TEXT(
            "unexpected key"
        )
    );
}
static MP_DEFINE_CONST_FUN_OBJ_KW(
    ncm_ipconfig_obj,
    1,
    ncm_ipconfig
);

static mp_obj_t ncm_config(
    size_t n_args,
    const mp_obj_t *args,
    mp_map_t *kwargs
) {
    (void)kwargs;

    if (
        n_args == 2
        && kwargs->used == 0
    ) {
        const char *key =
            mp_obj_str_get_str(
                args[1]
            );

        if (
            strcmp(
                key,
                "mac"
            ) == 0
        ) {
            return mp_obj_new_bytes(
                ncm_obj.mac,
                sizeof(ncm_obj.mac)
            );
        }
    }

    mp_raise_ValueError(
        MP_ERROR_TEXT(
            "unknown config param"
        )
    );
}
static MP_DEFINE_CONST_FUN_OBJ_KW(
    ncm_config_obj,
    1,
    ncm_config
);

static void ncm_stats_store_u32(
    mp_obj_t dict,
    qstr key,
    uint32_t value
) {
    mp_obj_dict_store(
        dict,
        MP_OBJ_NEW_QSTR(key),
        mp_obj_new_int_from_uint(
            value
        )
    );
}

static mp_obj_t ncm_stats(
    mp_obj_t self_in
) {
    ncm_obj_t *self =
        MP_OBJ_TO_PTR(
            self_in
        );

    mp_obj_t dict =
        mp_obj_new_dict(
            32
        );

    ncm_stats_store_u32(dict, MP_QSTR_rx_frames, self->rx_frames);
    ncm_stats_store_u32(dict, MP_QSTR_rx_bytes, self->rx_bytes);
    ncm_stats_store_u32(dict, MP_QSTR_rx_errors, self->rx_errors);

    ncm_stats_store_u32(dict, MP_QSTR_tx_frames, self->tx_frames);
    ncm_stats_store_u32(dict, MP_QSTR_tx_bytes, self->tx_bytes);
    ncm_stats_store_u32(dict, MP_QSTR_tx_errors, self->tx_errors);

    ncm_stats_store_u32(dict, MP_QSTR_rx_arp, self->rx_arp);
    ncm_stats_store_u32(dict, MP_QSTR_tx_arp, self->tx_arp);

    ncm_stats_store_u32(dict, MP_QSTR_rx_ipv4, self->rx_ipv4);
    ncm_stats_store_u32(dict, MP_QSTR_tx_ipv4, self->tx_ipv4);

    ncm_stats_store_u32(dict, MP_QSTR_rx_icmp, self->rx_icmp);
    ncm_stats_store_u32(dict, MP_QSTR_tx_icmp, self->tx_icmp);

    ncm_stats_store_u32(dict, MP_QSTR_rx_tcp, self->rx_tcp);
    ncm_stats_store_u32(dict, MP_QSTR_tx_tcp, self->tx_tcp);

    ncm_stats_store_u32(dict, MP_QSTR_rx_udp, self->rx_udp);
    ncm_stats_store_u32(dict, MP_QSTR_tx_udp, self->tx_udp);

    ncm_stats_store_u32(dict, MP_QSTR_last_rx_len, self->last_rx_len);
    ncm_stats_store_u32(dict, MP_QSTR_last_tx_len, self->last_tx_len);

    ncm_stats_store_u32(dict, MP_QSTR_last_rx_ethertype, self->last_rx_ethertype);
    ncm_stats_store_u32(dict, MP_QSTR_last_tx_ethertype, self->last_tx_ethertype);

    ncm_stats_store_u32(dict, MP_QSTR_last_rx_ip_proto, self->last_rx_ip_proto);
    ncm_stats_store_u32(dict, MP_QSTR_last_tx_ip_proto, self->last_tx_ip_proto);

    ncm_stats_store_u32(dict, MP_QSTR_last_rx_tcp_src_port, self->last_rx_tcp_src_port);
    ncm_stats_store_u32(dict, MP_QSTR_last_rx_tcp_dst_port, self->last_rx_tcp_dst_port);
    ncm_stats_store_u32(dict, MP_QSTR_last_rx_tcp_flags, self->last_rx_tcp_flags);

    ncm_stats_store_u32(dict, MP_QSTR_last_tx_tcp_src_port, self->last_tx_tcp_src_port);
    ncm_stats_store_u32(dict, MP_QSTR_last_tx_tcp_dst_port, self->last_tx_tcp_dst_port);
    ncm_stats_store_u32(dict, MP_QSTR_last_tx_tcp_flags, self->last_tx_tcp_flags);

    mp_obj_dict_store(
        dict,
        MP_OBJ_NEW_QSTR(MP_QSTR_mounted),
        mp_obj_new_bool(
            esp_ncm_transport_mounted()
        )
    );

    mp_obj_dict_store(
        dict,
        MP_OBJ_NEW_QSTR(MP_QSTR_stack_started),
        mp_obj_new_bool(
            self->stack_started
        )
    );

    mp_obj_dict_store(
        dict,
        MP_OBJ_NEW_QSTR(MP_QSTR_netif_up),
        mp_obj_new_bool(
            self->netif != NULL
            && esp_netif_is_netif_up(
                self->netif
            )
        )
    );

    return dict;
}

static MP_DEFINE_CONST_FUN_OBJ_1(
    ncm_stats_obj,
    ncm_stats
);

static const mp_rom_map_elem_t
ncm_locals_dict_table[] = {
    {
        MP_ROM_QSTR(MP_QSTR_status),
        MP_ROM_PTR(&ncm_status_obj)
    },

    {
        MP_ROM_QSTR(MP_QSTR_isconnected),
        MP_ROM_PTR(&ncm_isconnected_obj)
    },

    {
        MP_ROM_QSTR(MP_QSTR_active),
        MP_ROM_PTR(&ncm_active_obj)
    },

    {
        MP_ROM_QSTR(MP_QSTR_ifconfig),
        MP_ROM_PTR(&ncm_ifconfig_obj)
    },

    {
        MP_ROM_QSTR(MP_QSTR_ipconfig),
        MP_ROM_PTR(&ncm_ipconfig_obj)
    },

    {
        MP_ROM_QSTR(MP_QSTR_config),
        MP_ROM_PTR(&ncm_config_obj)
    },

    {
        MP_ROM_QSTR(MP_QSTR_stats),
        MP_ROM_PTR(&ncm_stats_obj)
    },
};

static MP_DEFINE_CONST_DICT(
    ncm_locals_dict,
    ncm_locals_dict_table
);

MP_DEFINE_CONST_OBJ_TYPE(
    mod_network_nic_type_ncm,
    MP_QSTR_USBD_NCM,
    MP_TYPE_FLAG_NONE,
    make_new, ncm_make_new,
    locals_dict, &ncm_locals_dict
);

#endif
