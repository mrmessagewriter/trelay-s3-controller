# Sprinklers1 custom ESP32-S3 board.

include(boards/mpconfigboard_esp32s3_common.cmake)

list(APPEND SDKCONFIG_DEFAULTS
    boards/sdkconfig.flash_qio_80m
    boards/sdkconfig.csi
)

# network.USBD_NCM enables MicroPython's built-in DHCP server by default so
# the USB host receives an address automatically.  The ESP32 port currently
# does not add this shared source itself, so include it as board source.
#
# The RP2 port includes the same source for its NCM-capable networking builds.
list(APPEND MICROPY_SOURCE_BOARD
    ${MICROPY_DIR}/shared/netutils/dhcpserver.c
)
