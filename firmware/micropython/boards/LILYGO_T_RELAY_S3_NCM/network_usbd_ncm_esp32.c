/*
 * ESP32-native MicroPython USB CDC-NCM backend for LILYGO_T_RELAY_S3_NCM.
 *
 * This intentionally uses ESP-IDF esp_netif as the network-stack boundary.
 * TinyUSB remains responsible for USB NCM framing/descriptors, while esp_netif
 * owns ARP, IPv4, DHCP server, ICMP, TCP and BSD sockets.
 *
 * USB subnet:
 *   device:  192.168.7.1/24
 *   clients: DHCP from ESP-IDF (normally 192.168.7.x)
 *   gateway: none
 */

#include <string.h>

#include "py/runtime.h"
#include "py/mperrno.h"

#if MICROPY_PY_NETWORK_USBD_NCM

#include "extmod/network_usbd_ncm.h"

#ifndef NO_QSTR
#include "tusb.h"
#endif

#include "esp_err.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_netif_defaults.h"

#include "shared/netutils/netutils.h"

const mp_obj_type_t mod_network_nic_type_ncm;

/* TinyUSB's NCM descriptors reference this symbol. */
uint8_t tud_network_mac_address[6] = {0x02, 0x00, 0x00, 0x00, 0x00, 0x01};

typedef struct _ncm_obj_t {
    mp_obj_base_t base;
    esp_netif_t *netif;
    bool init;
    bool active;
    uint8_t mac[6];
} ncm_obj_t;

static ncm_obj_t ncm_obj;

#define USB_NCM_IP_A 192
#define USB_NCM_IP_B 168
#define USB_NCM_IP_C 7
#define USB_NCM_IP_D 1

static esp_netif_ip_info_t ncm_ip_info;

/*
 * lwIP -> USB.
 *
 * esp_netif gives us a complete Ethernet frame. TinyUSB calls
 * tud_network_xmit_cb() to copy it into the NCM transmit buffer.
 */
static esp_err_t ncm_driver_transmit(void *handle, void *buffer, size_t len) {
    (void)handle;

    if (!ncm_obj.active || !tud_mounted()) {
        return ESP_ERR_INVALID_STATE;
    }

    if (len == 0 || len > UINT16_MAX) {
        return ESP_ERR_INVALID_SIZE;
    }

    if (!tud_network_can_xmit((uint16_t)len)) {
        return ESP_FAIL;
    }

    tud_network_xmit(buffer, (uint16_t)len);
    return ESP_OK;
}

/*
 * TinyUSB -> lwIP/ESP-IDF.
 *
 * esp_netif_receive() is the official ESP-IDF driver-to-TCP/IP handoff.
 */
bool tud_network_recv_cb(const uint8_t *src, uint16_t size) {
    if (!ncm_obj.init || !ncm_obj.active || ncm_obj.netif == NULL) {
        return false;
    }

    if (size == 0) {
        tud_network_recv_renew();
        return true;
    }

    esp_err_t err = esp_netif_receive(
        ncm_obj.netif,
        (void *)src,
        size,
        NULL
    );

    tud_network_recv_renew();

    return err == ESP_OK;
}

/*
 * TinyUSB requests bytes for a pending transmit.
 *
 * The buffer supplied by esp_netif remains valid while its transmit callback
 * is active, so no secondary heap allocation is required.
 */
uint16_t tud_network_xmit_cb(uint8_t *dst, void *ref, uint16_t arg) {
    if (dst == NULL || ref == NULL || arg == 0) {
        return 0;
    }

    memcpy(dst, ref, arg);
    return arg;
}

/*
 * Older Espressif TinyUSB revisions do not expose tud_network_link_state().
 * Keep the default NCM link state and let active() control the esp_netif side.
 */
bool tud_network_default_link_state_cb(void) {
    return ncm_obj.active;
}

static void ncm_raise_esp_error(esp_err_t err) {
    if (err == ESP_OK) {
        return;
    }

    if (err == ESP_ERR_NO_MEM) {
        mp_raise_OSError(MP_ENOMEM);
    }

    if (err == ESP_ERR_INVALID_ARG) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid argument"));
    }

    mp_raise_msg_varg(
        &mp_type_OSError,
        MP_ERROR_TEXT("ESP-NETIF error 0x%x"),
        (unsigned int)err
    );
}

static void ncm_start(void) {
    if (!ncm_obj.init || ncm_obj.netif == NULL || ncm_obj.active) {
        return;
    }

    /*
     * Setting the address while the interface is stopped avoids DHCP-server
     * restart races.
     */
    ncm_raise_esp_error(
        esp_netif_set_ip_info(ncm_obj.netif, &ncm_ip_info)
    );

    ncm_raise_esp_error(
        esp_netif_action_start(ncm_obj.netif, NULL, 0, NULL)
    );

    ncm_raise_esp_error(
        esp_netif_action_connected(ncm_obj.netif, NULL, 0, NULL)
    );

    esp_err_t dhcp_err = esp_netif_dhcps_start(ncm_obj.netif);
    if (
        dhcp_err != ESP_OK
        && dhcp_err != ESP_ERR_ESP_NETIF_DHCP_ALREADY_STARTED
    ) {
        ncm_raise_esp_error(dhcp_err);
    }

    ncm_obj.active = true;
}

static void ncm_stop(void) {
    if (!ncm_obj.init || ncm_obj.netif == NULL || !ncm_obj.active) {
        return;
    }

    esp_err_t dhcp_err = esp_netif_dhcps_stop(ncm_obj.netif);
    if (
        dhcp_err != ESP_OK
        && dhcp_err != ESP_ERR_ESP_NETIF_DHCP_ALREADY_STOPPED
    ) {
        ncm_raise_esp_error(dhcp_err);
    }

    ncm_raise_esp_error(
        esp_netif_action_disconnected(ncm_obj.netif, NULL, 0, NULL)
    );

    ncm_raise_esp_error(
        esp_netif_action_stop(ncm_obj.netif, NULL, 0, NULL)
    );

    ncm_obj.active = false;
}

static void ncm_init(void) {
    if (ncm_obj.init) {
        return;
    }

    memset(&ncm_obj, 0, sizeof(ncm_obj));
    ncm_obj.base.type = (mp_obj_type_t *)&mod_network_nic_type_ncm;

    /*
     * esp_netif_init() is idempotent in ESP-IDF: if lwIP is already running
     * it simply returns ESP_OK.
     */
    ncm_raise_esp_error(esp_netif_init());

    if (esp_read_mac(ncm_obj.mac, ESP_MAC_ETH) != ESP_OK) {
        mp_raise_OSError(MP_EIO);
    }

    /*
     * Use a locally administered address for the USB virtual Ethernet
     * interface while retaining the device-unique lower bytes.
     */
    ncm_obj.mac[0] &= 0xfe;
    ncm_obj.mac[0] |= 0x02;

    memcpy(
        tud_network_mac_address,
        ncm_obj.mac,
        sizeof(tud_network_mac_address)
    );

    IP4_ADDR(
        &ncm_ip_info.ip,
        USB_NCM_IP_A,
        USB_NCM_IP_B,
        USB_NCM_IP_C,
        USB_NCM_IP_D
    );

    IP4_ADDR(
        &ncm_ip_info.netmask,
        255,
        255,
        255,
        0
    );

    /*
     * No gateway: Windows must not route normal Internet traffic through the
     * sprinkler controller.
     */
    IP4_ADDR(
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
        .mtu = 0,
    };

    static esp_netif_driver_ifconfig_t driver_cfg = {
        .handle = (esp_netif_iodriver_handle)&ncm_obj,
        .transmit = ncm_driver_transmit,
        .transmit_wrap = NULL,
        .driver_free_rx_buffer = NULL,
        .driver_set_mac_filter = NULL,
    };

    esp_netif_config_t cfg = {
        .base = &base_cfg,
        .driver = &driver_cfg,
        .stack = ESP_NETIF_NETSTACK_DEFAULT_ETH,
    };

    ncm_obj.netif = esp_netif_new(&cfg);

    if (ncm_obj.netif == NULL) {
        mp_raise_OSError(MP_ENOMEM);
    }

    ncm_raise_esp_error(
        esp_netif_set_mac(
            ncm_obj.netif,
            ncm_obj.mac
        )
    );

    ncm_obj.init = true;

    ncm_start();
}

/*
 * Called by mod_network_init() before TinyUSB starts accepting host traffic.
 * The esp_netif object intentionally persists across MicroPython soft resets.
 */
void ncm_auto_init(void) {
    if (!ncm_obj.init) {
        ncm_init();
    } else if (!ncm_obj.active) {
        ncm_start();
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

    mp_arg_check_num(n_args, n_kw, 0, 0, false);

    if (!ncm_obj.init) {
        ncm_init();
    }

    return MP_OBJ_FROM_PTR(&ncm_obj);
}

static mp_obj_t ncm_status(mp_obj_t self_in) {
    ncm_obj_t *self = MP_OBJ_TO_PTR(self_in);

    return MP_OBJ_NEW_SMALL_INT(
        self->active
        && self->netif != NULL
        && esp_netif_is_netif_up(self->netif)
    );
}
static MP_DEFINE_CONST_FUN_OBJ_1(ncm_status_obj, ncm_status);

static mp_obj_t ncm_isconnected(mp_obj_t self_in) {
    ncm_obj_t *self = MP_OBJ_TO_PTR(self_in);

    return mp_obj_new_bool(
        self->active
        && self->netif != NULL
        && esp_netif_is_netif_up(self->netif)
        && tud_connected()
    );
}
static MP_DEFINE_CONST_FUN_OBJ_1(ncm_isconnected_obj, ncm_isconnected);

static mp_obj_t ncm_active(size_t n_args, const mp_obj_t *args) {
    ncm_obj_t *self = MP_OBJ_TO_PTR(args[0]);

    if (n_args == 1) {
        return mp_obj_new_bool(self->active);
    }

    if (mp_obj_is_true(args[1])) {
        ncm_start();
    } else {
        ncm_stop();
    }

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(ncm_active_obj, 1, 2, ncm_active);

static mp_obj_t ncm_ifconfig(size_t n_args, const mp_obj_t *args) {
    ncm_obj_t *self = MP_OBJ_TO_PTR(args[0]);

    if (self->netif == NULL) {
        mp_raise_OSError(MP_ENODEV);
    }

    esp_netif_ip_info_t info;
    esp_netif_dns_info_t dns;

    ncm_raise_esp_error(
        esp_netif_get_ip_info(self->netif, &info)
    );

    memset(&dns, 0, sizeof(dns));
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

        return mp_obj_new_tuple(4, tuple);
    }

    if (
        !mp_obj_is_type(args[1], &mp_type_tuple)
        && !mp_obj_is_type(args[1], &mp_type_list)
    ) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid arguments"));
    }

    mp_obj_t *items;
    mp_obj_get_array_fixed_n(args[1], 4, &items);

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

    bool was_active = self->active;

    if (was_active) {
        ncm_stop();
    }

    ncm_ip_info = new_info;

    ncm_raise_esp_error(
        esp_netif_set_ip_info(
            self->netif,
            &ncm_ip_info
        )
    );

    if (was_active) {
        ncm_start();
    }

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(ncm_ifconfig_obj, 1, 2, ncm_ifconfig);

static mp_obj_t ncm_ipconfig(
    size_t n_args,
    const mp_obj_t *args,
    mp_map_t *kwargs
) {
    ncm_obj_t *self = MP_OBJ_TO_PTR(args[0]);

    if (self->netif == NULL) {
        mp_raise_OSError(MP_ENODEV);
    }

    if (kwargs->used != 0) {
        mp_raise_ValueError(
            MP_ERROR_TEXT("setting ipconfig is not supported")
        );
    }

    if (n_args != 2) {
        mp_raise_TypeError(
            MP_ERROR_TEXT("must query one param")
        );
    }

    qstr key = mp_obj_str_get_qstr(args[1]);

    esp_netif_ip_info_t info;
    ncm_raise_esp_error(
        esp_netif_get_ip_info(self->netif, &info)
    );

    if (key == MP_QSTR_addr4) {
        mp_obj_t tuple[2] = {
            netutils_format_ipv4_addr(
                (uint8_t *)&info.ip,
                NETUTILS_BIG
            ),
            MP_OBJ_NEW_SMALL_INT(24),
        };

        return mp_obj_new_tuple(2, tuple);
    }

    if (key == MP_QSTR_gw4) {
        return netutils_format_ipv4_addr(
            (uint8_t *)&info.gw,
            NETUTILS_BIG
        );
    }

    if (key == MP_QSTR_dns) {
        esp_netif_dns_info_t dns;
        memset(&dns, 0, sizeof(dns));

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

    mp_raise_ValueError(MP_ERROR_TEXT("unexpected key"));
}
static MP_DEFINE_CONST_FUN_OBJ_KW(ncm_ipconfig_obj, 1, ncm_ipconfig);

static mp_obj_t ncm_config(
    size_t n_args,
    const mp_obj_t *args,
    mp_map_t *kwargs
) {
    if (n_args == 2 && kwargs->used == 0) {
        const char *key = mp_obj_str_get_str(args[1]);

        if (strcmp(key, "mac") == 0) {
            return mp_obj_new_bytes(
                ncm_obj.mac,
                sizeof(ncm_obj.mac)
            );
        }
    }

    mp_raise_ValueError(
        MP_ERROR_TEXT("unknown config param")
    );
}
static MP_DEFINE_CONST_FUN_OBJ_KW(ncm_config_obj, 1, ncm_config);

static const mp_rom_map_elem_t ncm_locals_dict_table[] = {
    { MP_ROM_QSTR(MP_QSTR_status), MP_ROM_PTR(&ncm_status_obj) },
    { MP_ROM_QSTR(MP_QSTR_isconnected), MP_ROM_PTR(&ncm_isconnected_obj) },
    { MP_ROM_QSTR(MP_QSTR_active), MP_ROM_PTR(&ncm_active_obj) },
    { MP_ROM_QSTR(MP_QSTR_ifconfig), MP_ROM_PTR(&ncm_ifconfig_obj) },
    { MP_ROM_QSTR(MP_QSTR_ipconfig), MP_ROM_PTR(&ncm_ipconfig_obj) },
    { MP_ROM_QSTR(MP_QSTR_config), MP_ROM_PTR(&ncm_config_obj) },
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
