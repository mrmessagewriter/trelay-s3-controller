# MicroPython USB-NCM Runtime

TRelay-S3-Controller can operate over Wi-Fi with a normal compatible MicroPython installation. The custom runtime described here is only required when the controller should also be reachable as a network device over its USB connection.

## Runtime design

The custom board/runtime is built for:

```text
Board:   LILYGO_T_RELAY_S3_NCM
Variant: SPIRAM_OCT
```

It provides:

- LILYGO T-Relay ESP32-S3 support;
- 8 MiB Octal PSRAM;
- USB CDC serial console;
- USB CDC-NCM networking through `network.USBD_NCM`;
- the ESP32/lwIP/TinyUSB compatibility required by the current MicroPython source used by this project.

The build retains MicroPython's upstream `extmod/network_usbd_ncm.c` implementation and applies only the ESP32 integration fixes required by the selected source/toolchain versions.

## USB network

The controller uses a private point-to-point IPv4 network rather than exposing the USB interface as an Internet gateway:

```text
Controller: 172.31.77.1/24
Windows:    172.31.77.2/24
Gateway:    none
DNS:        none
```

The device-side values are configured in:

```text
firmware/micropython/micropython_build.json
```

with:

```json
"ncm_ipv4_address": "172.31.77.1",
"ncm_ipv4_netmask": "255.255.255.0"
```

TRelay-S3-Controller prints the active USB address during startup when USB NCM is available.

## Windows host configuration

Run the following from an Administrator PowerShell window:

```powershell
.\firmware\tools\configure_controller_usb.ps1
```

The helper finds the MicroPython USB network adapter, configures `172.31.77.2/24`, adds the controller route, marks the network Private when possible, and creates a narrowly scoped firewall allow rule.

To restore the adapter to DHCP later:

```powershell
.\firmware\tools\restore_controller_usb_dhcp.ps1
```

The static USB adapter has no gateway and no DNS server, so normal Internet traffic continues to use the computer's normal network path.

## Build the runtime

From the repository root:

```cmd
python firmware\tools\build_micropython_ncm.py --bootstrap --clean
```

On Windows the build script relaunches itself inside WSL. Subsequent builds can omit `--bootstrap` when ESP-IDF and its toolchain are already installed.

Output:

```text
firmware/dist/micropython/LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT.bin
```

The exact MicroPython commit used is printed by the build script so preview builds can be reproduced and debugged.

## Flashing

Install esptool if necessary:

```cmd
python -m pip install esptool
```

For a first install, erase flash and write the combined image at address `0`:

```cmd
python -m esptool --chip esp32s3 --port COM3 erase-flash
python -m esptool --chip esp32s3 --port COM3 write-flash 0 firmware\dist\micropython\LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT.bin
```

Erasing flash also erases the writable MicroPython filesystem. It is normally required only for a clean runtime installation, not for routine application updates.

## Runtime check

At the MicroPython REPL:

```python
import network
ncm = network.USBD_NCM()
print("active:", ncm.active())
print("connected:", ncm.isconnected())
print("status:", ncm.status())
print("ifconfig:", ncm.ifconfig())
```

The expected controller-side address is `172.31.77.1` with a `255.255.255.0` netmask.

## Version stream

The custom MicroPython runtime has a release version independent from the TRelay-S3-Controller application. The next release number is stored in:

```text
firmware/tools/next_micropython_version.json
```

GitHub release assets are named like:

```text
LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT-v1.0.15.bin
```
