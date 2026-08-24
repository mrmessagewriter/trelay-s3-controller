# MicroPython board definition:
# LILYGO_T_RELAY_S3_NCM
#
# The ESP32 top-level CMake file includes this file before esp32_common.cmake
# defines MICROPY_DIR. Do not use ${MICROPY_DIR} for board-added source paths
# in this file.

include(boards/mpconfigboard_esp32s3_common.cmake)

list(APPEND SDKCONFIG_DEFAULTS
    boards/sdkconfig.flash_qio_80m
    boards/sdkconfig.csi
)

# This file lives at:
#   <micropython-root>/ports/esp32/boards/LILYGO_T_RELAY_S3_NCM
#
# Four parent directories above CMAKE_CURRENT_LIST_DIR is the MicroPython root.
get_filename_component(
    LILYGO_T_RELAY_MICROPY_ROOT
    "${CMAKE_CURRENT_LIST_DIR}/../../../.."
    ABSOLUTE
)

set(
    LILYGO_T_RELAY_DHCPSERVER_SOURCE
    "${LILYGO_T_RELAY_MICROPY_ROOT}/shared/netutils/dhcpserver.c"
)

if(NOT EXISTS "${LILYGO_T_RELAY_DHCPSERVER_SOURCE}")
    message(
        FATAL_ERROR
        "LILYGO_T_RELAY_S3_NCM could not find MicroPython DHCP server source: "
        "${LILYGO_T_RELAY_DHCPSERVER_SOURCE}"
    )
endif()

# network.USBD_NCM uses MicroPython's small DHCP server implementation.
# The ESP32 port does not currently include this source by default.
list(APPEND MICROPY_SOURCE_BOARD
    "${LILYGO_T_RELAY_DHCPSERVER_SOURCE}"
)
