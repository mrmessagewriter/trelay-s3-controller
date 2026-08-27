# USB CDC-NCM networking on MicroPython and ESP32-S3

TRelay-S3-Controller supports two independent ways to reach the device over HTTP:

- Wi-Fi on the local network;
- USB CDC-NCM, where the ESP32-S3 appears to the host computer as a USB network adapter.

The USB path is optional. The application still works over Wi-Fi without it. The custom runtime exists for installations where direct USB access is useful for configuration, maintenance, development, or operation in locations where Wi-Fi is unavailable.

## Why use USB networking instead of only a serial console?

A normal MicroPython serial console is excellent for development, but it is not the same thing as having a network connection.

CDC-NCM gives the host computer an actual IP interface. Once that interface is up, the same HTTP server and REST API used over Wi-Fi can be reached directly over the USB cable.

For this project that means the browser UI does not need a special desktop application or serial protocol. The controller continues to speak ordinary HTTP.

```text
Browser / REST client
        |
        | HTTP
        v
Host USB network adapter
        |
        | USB CDC-NCM
        v
ESP32-S3
        |
        +--> Microdot on 0.0.0.0:80
        +--> diagnostic TCP listener on 0.0.0.0:8081
```

## The USB point-to-point network

TRelay-S3-Controller uses a small private IPv4 network for the USB link:

```text
Controller: 172.31.77.1/24
Windows:    172.31.77.2/24
Gateway:    none
DNS:        none
```

There is deliberately no gateway. The USB interface is only a directly attached management network and should not become the host computer's route to the Internet.

The Windows-side helper is:

```powershell
.\firmware\tools\configure_controller_usb.ps1
```

It configures the MicroPython USB network adapter, creates the host route to the controller, marks the interface Private when Windows exposes a network profile, and adds a narrowly scoped firewall rule.

To return the adapter to DHCP later:

```powershell
.\firmware\tools\restore_controller_usb_dhcp.ps1
```

## The MicroPython runtime

The runtime is built for:

```text
Board:   LILYGO_T_RELAY_S3_NCM
Variant: SPIRAM_OCT
```

and includes:

- ESP32-S3 support for the LILYGO T-Relay board;
- 8 MiB Octal PSRAM support;
- USB CDC serial;
- USB CDC-NCM through `network.USBD_NCM`;
- the ESP32/lwIP/TinyUSB integration required by the selected MicroPython source revision.

The build retains MicroPython's upstream `extmod/network_usbd_ncm.c` implementation and applies the ESP32 compatibility work in the project build process rather than replacing the upstream NCM implementation wholesale.

The relevant project files are:

```text
firmware/tools/build_micropython_ncm.py
firmware/micropython/micropython_build.json
firmware/micropython/boards/LILYGO_T_RELAY_S3_NCM/
firmware/source/boot.py
```

## Why `boot.py` matters

The USB composite device is enumerated very early during startup. For NCM, information such as the network interface identity must be ready before the host finishes USB enumeration.

TRelay-S3-Controller therefore includes a small `/boot.py` in the deployment package. It prepares the NCM object early enough for the USB descriptor path without moving full network-stack startup into an unsafe pre-runtime phase.

The normal application later activates and uses the interface when `network.USBD_NCM` is available.

This keeps the application portable: a standard compatible MicroPython runtime can run the Wi-Fi functionality, while the custom runtime adds the direct USB network path.

## Building the custom runtime

On Windows:

```cmd
python firmware\tools\build_micropython_ncm.py --bootstrap --clean
```

The builder uses WSL for the ESP-IDF/MicroPython build environment. The first run with `--bootstrap` installs or prepares the required toolchain and source dependencies. Later builds can normally omit `--bootstrap`.

The resulting combined image is written to:

```text
firmware/dist/micropython/LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT.bin
```

The builder also prints the exact MicroPython revision used so a build can be reproduced later.

## Flashing the runtime

Install Espressif's Python flashing tool:

```cmd
python -m pip install esptool
```

Then, for a clean first install:

```cmd
python -m esptool --chip esp32s3 --port COM3 erase-flash
python -m esptool --chip esp32s3 --port COM3 write-flash 0 firmware\dist\micropython\LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT.bin
```

Replace `COM3` with the serial port assigned to the ESP32-S3.

Erasing flash also erases the writable MicroPython filesystem, so it should not be part of routine application updates.

## Checking NCM from the REPL

Once the custom runtime is installed:

```python
import network

ncm = network.USBD_NCM()
print("active:", ncm.active())
print("connected:", ncm.isconnected())
print("status:", ncm.status())
print("ifconfig:", ncm.ifconfig())
```

The controller-side IPv4 configuration should report:

```text
172.31.77.1
255.255.255.0
```

## Application behavior

The TRelay-S3-Controller application binds Microdot to:

```text
0.0.0.0:80
```

so the same HTTP listener can serve requests arriving from either Wi-Fi or USB NCM.

The application also includes a small raw TCP diagnostic listener on port `8081`. This is useful when debugging because it bypasses Microdot and helps distinguish an application-framework problem from a lower-level TCP/NCM problem.

Useful tests from Windows are:

```powershell
ping 172.31.77.1
curl.exe -v --max-time 5 --noproxy "*" http://172.31.77.1:8081/
curl.exe -v --max-time 5 --noproxy "*" http://172.31.77.1/api/status
```

## A useful debugging lesson: VPNs and link-local addressing

During development, host VPN software was found to be capable of interfering with directly attached USB network traffic, especially when the USB interface used a `169.254.x.x` link-local address.

Moving the project to the explicit private subnet `172.31.77.0/24`, with no gateway and a host-specific route, makes the intent of the interface much clearer to the operating system and networking software.

That design also prevents the USB adapter from accidentally becoming a default Internet path.

## Separating runtime and application releases

The custom MicroPython image and the controller application have independent version streams.

MicroPython runtime releases use names similar to:

```text
MicroPython LILYGO_T_RELAY_S3_NCM v1.0.15
LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT-v1.0.15.bin
```

Application releases use names similar to:

```text
LilyGo T-Relay-S3 Controller Firmware v1.0.23
LilyGo-T-Relay-S3-Controller-Firmware-v1.0.23.zip
```

Keeping those releases separate means users who only use Wi-Fi do not need to update the custom runtime every time the application changes.

## Where to go next

- [Project README](../README.md)
- [MicroPython USB-NCM runtime documentation](../firmware/docs/MICROPYTHON_USB_NCM.md)
- [HTTP, Wi-Fi, and USB documentation](../firmware/docs/HTTP_WIFI_AND_USB.md)
- [MicroPython build tool](../firmware/tools/build_micropython_ncm.py)
- [Windows USB configuration helper](../firmware/tools/configure_controller_usb.ps1)
