# Match MicroPython's ESP32_GENERIC_S3 SPIRAM_OCT variant.

list(APPEND SDKCONFIG_DEFAULTS
    boards/sdkconfig.240mhz
    boards/sdkconfig.spiram_oct
)

list(APPEND MICROPY_DEF_BOARD
    MICROPY_HW_BOARD_NAME="LILYGO T-Relay S3 NCM with Octal-SPIRAM"
)
