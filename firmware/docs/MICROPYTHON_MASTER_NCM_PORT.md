# ESP32 Port Notes for Upstream MicroPython USB NCM

This tree intentionally follows MicroPython `master` instead of carrying a
separate NCM network stack.

At package generation time, upstream `network_usbd_ncm.c` owns:

- the NCM singleton;
- pre-enumeration auto-initialization;
- `active()` / `status()` / `isconnected()` semantics;
- link-local `169.254.x.1` address generation;
- the small DHCP server;
- TinyUSB carrier/link notifications.

The ESP32 build helper patches only integration seams that are not yet provided
by the ESP32 port. Each patch is structural and fails the build if the expected
upstream source shape changes, rather than silently applying an unsafe fallback.

In particular, the builder never defines `tud_network_link_state()` as a no-op
and never replaces `extmod/network_usbd_ncm.c` with a custom ESP-NETIF backend.
When master/TinyUSB gain native ESP32 support for these seams, the compatibility
steps are designed to detect existing support and can be removed.
## ESP32 board CMake ordering

MicroPython loads `mpconfigboard.cmake` from the ESP32 top-level CMake file before
`esp32_common.cmake` initializes `MICROPY_DIR`. Any board-added source needed at
that stage must therefore use a path derived from `CMAKE_CURRENT_LIST_DIR` (or
another already-defined value), not `${MICROPY_DIR}`. The board definition uses
that rule for `shared/netutils/dhcpserver.c`, and the build helper performs an
early existence check after installing the board into the MicroPython checkout.

