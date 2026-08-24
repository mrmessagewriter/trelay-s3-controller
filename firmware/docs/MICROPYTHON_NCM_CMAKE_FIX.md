# USB-NCM ESP32 CMake Fix

## Failure

The custom board originally used:

```cmake
${MICROPY_DIR}/shared/netutils/dhcpserver.c
```

inside `mpconfigboard.cmake`.

For the ESP32 port, the top-level MicroPython CMake file includes the board
configuration before `esp32_common.cmake` initializes `MICROPY_DIR`. Therefore
that expression became:

```text
/shared/netutils/dhcpserver.c
```

and CMake failed with:

```text
Cannot find source file:
/shared/netutils/dhcpserver.c
```

## Correct path

The custom board now derives the MicroPython repository root from
`CMAKE_CURRENT_LIST_DIR`, which is already valid when the board configuration
is processed:

```cmake
get_filename_component(
    LILYGO_T_RELAY_MICROPY_ROOT
    "${CMAKE_CURRENT_LIST_DIR}/../../../.."
    ABSOLUTE
)

list(APPEND MICROPY_SOURCE_BOARD
    "${LILYGO_T_RELAY_MICROPY_ROOT}/shared/netutils/dhcpserver.c"
)
```

## ESP-IDF version

The custom build is restored to:

```text
ESP-IDF v5.5.2
```

because current MicroPython `master` expects 5.5.2 in its ESP32-S3 component
lockfile.

Using IDF 5.3 caused the build system to rewrite:

```text
dependencies.lock.esp32s3
```

from 5.5.2 to 5.3.0.

The builder now also resets an existing dependency checkout before each build
so a lockfile modified by an earlier failed build does not contaminate the next
run.
