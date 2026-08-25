# MicroPython Master USB-NCM Runtime

Sprinklers1 builds its LILYGO T-Relay ESP32-S3 runtime from the current
MicroPython `master` branch.

## Design rule

The build uses MicroPython's upstream `extmod/network_usbd_ncm.c` as the NCM
implementation. It no longer copies the old Sprinklers1
`network_usbd_ncm_esp32.c` over the upstream source.

The ESP32 port does not currently expose all of the generic `MICROPY_PY_LWIP`
helpers expected by upstream NCM, so `build_micropython_ncm.py` applies a narrow
build-time compatibility shim. The shim:

- Uses ESP-IDF lwIP core locking.
- Routes NCM receive frames through `tcpip_input()`.
- Gets the ESP32 Ethernet MAC with `esp_read_mac()`.
- Supplies query-only `ifconfig()` / `ipconfig()` helpers.
- Compiles MicroPython's shared DHCP server for NCM.
- Preserves upstream NCM `ncm_auto_init()`, `active()`, `isconnected()`, link
  state signaling, DHCP behavior, and link-local address generation.

The build helper also detects the TinyUSB NCM API available in the ESP32
managed component. If MicroPython's pinned TinyUSB predates dynamic NCM carrier
signaling, the builder backports the link-state API rather than stubbing it.

## USB address

Upstream MicroPython derives a deterministic link-local controller address from
the device MAC:

```text
169.254.x.1/16
```

The exact third octet differs by device. Do not hard-code the address.
Sprinklers1 prints it at startup:

```text
USB IPv4: 169.254.x.1
```

The NCM DHCP server assigns the Windows host an address on the same USB link and
does not advertise the USB device as a default gateway.

## Build

From the repository root:

```cmd
python firmware\tools\build_micropython_ncm.py --bootstrap --clean
```

On Windows the script relaunches itself inside WSL. Subsequent builds can omit
`--bootstrap` when ESP-IDF and its toolchain are already present.

Output:

```text
firmware/dist/micropython/LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT.bin
```

The exact MicroPython commit used is printed by the build script so a preview
build can be reproduced/debugged.

## First NCM test after flashing

Before installing Sprinklers1, verify the runtime at the REPL:

```python
import network
ncm = network.USBD_NCM()
print("active:", ncm.active())
print("connected:", ncm.isconnected())
print("status:", ncm.status())
print("ifconfig:", ncm.ifconfig())
```

`active()` should already be `True` from boot. Do not call `active(True)` merely
to initialize NCM; upstream master auto-initializes it before USB enumeration.

On Windows, `Get-NetAdapter` should show the MicroPython USB network adapter as
`Up` with a non-zero link speed once the host has configured NCM.

## Version stream

The custom board runtime has a release version independent from the Sprinklers1
application. The next release number is stored in:

```text
firmware/tools/next_micropython_version.json
```

GitHub release assets are named like:

```text
LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT-v1.0.0.bin
```
