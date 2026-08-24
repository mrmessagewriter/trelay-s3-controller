# MicroPython LILYGO_T_RELAY_S3_NCM

This repository contains a custom MicroPython board build for the
LILYGO T-Relay ESP32-S3.

## Build identity

```text
Board:   LILYGO_T_RELAY_S3_NCM
Variant: SPIRAM_OCT
```

The application name `Sprinklers1` is not used for the MicroPython runtime.

## Features

The custom board keeps the ESP32-S3 Octal-PSRAM configuration and enables:

```c
#define MICROPY_PY_NETWORK_USBD_NCM (1)
```

which exposes:

```python
network.USBD_NCM
```

## Local output

```text
firmware/dist/micropython/LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT.bin
```

## GitHub Action

The runtime has its own workflow:

```text
.github/workflows/build-micropython-release.yml
```

and its own release/version stream.

The GitHub build workspace is:

```text
$HOME/micropython-lilygo-t-relay-s3-ncm-build
```

It is intentionally not named after the Sprinklers1 application.

## ESP-IDF

The current build configuration uses:

```text
ESP-IDF v5.5.2
```

to match the current MicroPython `master` ESP32-S3 dependency lockfile.

## DHCP source

`network.USBD_NCM` requires MicroPython's small DHCP server implementation.
The custom board adds:

```text
shared/netutils/dhcpserver.c
```

to the ESP32 build.

The board CMake derives the MicroPython repository root from
`CMAKE_CURRENT_LIST_DIR` because `MICROPY_DIR` is not yet defined when
`mpconfigboard.cmake` is first processed.
