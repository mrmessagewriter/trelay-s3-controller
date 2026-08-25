# MicroPython board definition: LILYGO_T_RELAY_S3_NCM
include(boards/mpconfigboard_esp32s3_common.cmake)

list(APPEND SDKCONFIG_DEFAULTS
    "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.usbd_ncm"
    boards/sdkconfig.flash_qio_80m
    boards/sdkconfig.csi
)

# The ESP32 port does not normally compile MicroPython's shared DHCP server,
# but upstream network_usbd_ncm.c uses it. Board CMake files are loaded before
# esp32_common.cmake initializes MICROPY_DIR, so derive the repository root from
# this board directory instead of using ${MICROPY_DIR} here.
get_filename_component(
    SPRINKLERS1_MICROPY_DIR
    "${CMAKE_CURRENT_LIST_DIR}/../../../.."
    ABSOLUTE
)
list(APPEND MICROPY_SOURCE_SHARED
    "${SPRINKLERS1_MICROPY_DIR}/shared/netutils/dhcpserver.c"
)
