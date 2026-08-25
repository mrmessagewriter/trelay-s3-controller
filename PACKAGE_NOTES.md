# Sprinklers1 Master-NCM Source Package

This package contains the complete Sprinklers1 source tree used for the next
build after application firmware 1.0.21.

## MicroPython runtime direction

- MicroPython source ref: `master`
- Board: `LILYGO_T_RELAY_S3_NCM`
- Variant: `SPIRAM_OCT`
- MicroPython's upstream `extmod/network_usbd_ncm.c` remains the NCM driver.
- The retired `network_usbd_ncm_esp32.c` replacement backend is not included.
- The build helper applies narrowly scoped ESP32/lwIP and TinyUSB compatibility
  glue and fails if expected upstream source anchors change.
- USB controller addressing is discovered at runtime; Sprinklers1 does not
  hard-code `192.168.7.1`.


## Build-system correction from diagnostics

A GitHub Actions failure diagnostics archive showed CMake trying to compile
`/shared/netutils/dhcpserver.c`. The board file had used `${MICROPY_DIR}` before
MicroPython initializes that variable. The board now derives the MicroPython
repository root from `CMAKE_CURRENT_LIST_DIR`, and the build helper verifies the
resolved DHCP source before invoking ESP-IDF.

## Application source

The application source is the current dual-network diagnostic revision with:

- six-relay startup test;
- Wi-Fi plus USB NCM HTTP binding on `0.0.0.0`;
- Microdot on port 80;
- raw TCP diagnostic listener on port 8081;
- NTP, weather, events, persistent configuration and logs;
- readiness LED behavior tied to the TCP diagnostic listener.

## Version counters

- Next Sprinklers1 application version: `1.0.22`
- Next MicroPython board-runtime release version: `1.0.8`

## Validation performed when this package was generated

- All Python files compile with CPython's parser.
- All JSON files parse successfully.
- Both GitHub Actions YAML workflows parse successfully.
- `build_firmware_deployment.py` successfully built and verified a test
  `main.zip` from the included `firmware/source` tree.
- The TinyUSB NCM carrier-state backport passed a structural synthetic-source
  patch test.
- The final source ZIP was integrity-tested after creation.

An ESP32 toolchain/hardware flash test was not run in the packaging environment,
because the environment cannot fetch the external MicroPython/ESP-IDF sources.
The normal local/GitHub build performs those fetches and compilation steps.
