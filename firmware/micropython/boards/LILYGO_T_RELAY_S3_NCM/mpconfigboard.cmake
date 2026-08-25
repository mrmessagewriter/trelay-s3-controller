# MicroPython board definition: LILYGO_T_RELAY_S3_NCM
include(boards/mpconfigboard_esp32s3_common.cmake)

list(APPEND SDKCONFIG_DEFAULTS
    "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.usbd_ncm"
    boards/sdkconfig.flash_qio_80m
    boards/sdkconfig.csi
)

# The ESP32 port does not normally compile MicroPython's shared DHCP server,
# but upstream network_usbd_ncm.c uses it. The build helper adjusts only the
# source guard so it can be compiled without enabling MICROPY_PY_LWIP globally.
list(APPEND MICROPY_SOURCE_SHARED
    ${MICROPY_DIR}/shared/netutils/dhcpserver.c
)
