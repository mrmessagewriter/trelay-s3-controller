# TRelay-S3-Controller

A MicroPython application for the **LILYGO T-Relay ESP32-S3** that turns the six-relay board into a network-connected relay controller with a built-in web UI, scheduling, event logging, optional weather-aware controls, Wi-Fi, and optional USB networking.

This repository contains both the application firmware and the supporting build/deployment tools. The instructions below focus on building and deploying the **TRelay-S3-Controller application firmware**, with a separate section for the optional custom MicroPython runtime used for USB networking.

This was written initially as a sprinkler control system, which is why there is so much support for things which a sprinkler system would require.  I may peel those out some day, but it is still functional as a relay control timer system, you just don't have use the sprinkler features along with is all. 

## Features

- Controls all six relay outputs on the LILYGO T-Relay ESP32-S3.
- Browser-based relay control and configuration.
- REST API through Microdot.
- Scheduled relay events by day and time.
- Relay On, Relay Off, All Relays On, All Relays Off, and GET URL events.
- Optional temperature, rain, and wind conditions for scheduled events.
- One-shot **Skip Next** support.
- Persistent event definitions and event logs.
- NTP time synchronization.
- Optional weather lookup by configured location.
- Wi-Fi station networking.
- Optional USB CDC-NCM networking for direct configuration and control over USB.
- Versioned firmware packages with SHA-256 verification.
- Safe staged deployment that preserves device configuration and event data.

## Hardware

Target board:

- **LILYGO T-Relay ESP32-S3**, six-relay model
- 16 MiB flash
- 8 MiB Octal PSRAM
- Relay outputs driven through the board's 74HC595 shift register

TRelay-S3-Controller can operate over Wi-Fi without the project's custom USB-NCM MicroPython runtime. The custom runtime is only required when you want the controller to expose a network connection over its USB port.

See [firmware/docs/HARDWARE.md](firmware/docs/HARDWARE.md) for GPIO and relay details.

## Optional MicroPython runtime for USB networking

### When do I need it?

You only need the project's custom MicroPython build if you want to communicate with **TRelay-S3-Controller over USB as a network connection**.  The primary reason for this, is when you want to configure the WiFi, although it can be managed by configuration file, it can also be done through here.   Also it allows you to not use WiFi with the device.  So if the device was very far away from WiFi, you can program it in that location. 

With the custom runtime installed, connecting the ESP32-S3 to a computer over USB exposes a CDC-NCM network adapter in addition to the normal serial console. The web UI and REST API can then be reached directly over USB without requiring Wi-Fi.

If you plan to use the controller only over Wi-Fi, the application detects that `network.USBD_NCM` is unavailable and continues without USB networking.

### What the custom runtime provides

The project-specific build is based on MicroPython for the ESP32-S3 and adds the board/runtime configuration needed for USB networking, including:

- LILYGO T-Relay ESP32-S3 support.
- 8 MiB Octal PSRAM (`SPIRAM_OCT`).
- USB CDC serial console.
- USB CDC-NCM networking through `network.USBD_NCM`.
- The USB controller-side address used by this project: `172.31.77.1/24`.

The MicroPython runtime has its **own version stream**, separate from the TRelay-S3-Controller application firmware.

### Download a prebuilt MicroPython runtime

The easiest option is to download the latest GitHub release whose name begins with:

```text
MicroPython LILYGO_T_RELAY_S3_NCM
```

from the repository's [Releases](https://github.com/mrmessagewriter/trelay-s3-controller/releases) page.

The binary asset is named like:

```text
LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT-vX.Y.Z.bin
```

### Flash the MicroPython runtime

Install `esptool` if needed:

```cmd
python -m pip install esptool
```

Put the ESP32-S3 into its ROM bootloader if necessary, then identify the COM port:

```cmd
python -m serial.tools.list_ports
```

For a first install, erase the existing flash:

```cmd
python -m esptool --chip esp32s3 --port COM3 erase-flash
```

Then flash the downloaded MicroPython binary at address `0`:

```cmd
python -m esptool --chip esp32s3 --port COM3 write-flash 0 LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT-vX.Y.Z.bin
```

Replace `COM3` and the filename with the values for your system.

> **Note:** `erase-flash` removes the writable MicroPython filesystem, including any existing application, configuration, and event data. It is normally used for the initial MicroPython installation, not for routine application updates.

After MicroPython is installed and the board restarts, deploy the TRelay-S3-Controller application using the tools described below.

### Build the custom MicroPython runtime yourself

This is separate from building the TRelay-S3-Controller application firmware.

From the repository root:

```cmd
python firmware\tools\build_micropython_ncm.py --bootstrap --clean
```

On Windows the MicroPython builder uses WSL for the ESP-IDF/MicroPython build environment.

The resulting binary is written to:

```text
firmware/dist/micropython/LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT.bin
```

For more detail, see [firmware/docs/MICROPYTHON_USB_NCM.md](firmware/docs/MICROPYTHON_USB_NCM.md).

## Repository layout

```text
firmware/
  source/
    boot.py
    device_loader_main.py
    main.py
    events.py
    weather.py
    config.json
    lib/
      microdot.py
    static/
      index.html
      setup.html
      events.html

  tools/
    build_firmware_deployment.py
    upload_controller_firmware.py
    configure_controller_usb.ps1
    restore_controller_usb_dhcp.ps1
    diagnose_lilygo_usb_ncm.ps1
    wipe_device.py
    next_firmware_version.json
    next_micropython_version.json

  dist/
    main.zip          # generated application image
    deployment.zip    # generated deployable package

  docs/
    ARCHITECTURE.md
    BUILD_AND_DEPLOY.md
    EVENTS_AND_PERSISTENCE.md
    HARDWARE.md
    HTTP_WIFI_AND_USB.md
```

`firmware/dist/` is generated by the build tools and is not source code.

## Host requirements

Python 3 is required on the computer used to build or upload firmware.

Install the deployment dependencies:

```cmd
python -m pip install mpremote pyserial
```

Before uploading, close Thonny, serial monitors, or any other program that currently has the ESP32 COM port open.

To list available serial ports on Windows:

```cmd
python -m serial.tools.list_ports
```

## Building the application firmware

From the repository root:

```cmd
python firmware\tools\build_firmware_deployment.py
```

The builder reads the application from:

```text
firmware/source/
```

and creates:

```text
firmware/dist/main.zip
firmware/dist/deployment.zip
```

### `main.zip`

`main.zip` is the application image mounted by the device-side loader. It contains the application code, web UI, libraries, and an automatically generated `firmware_info.json` manifest.

The files are stored uncompressed (`ZIP_STORED`) so the device can use the archive directly.

### `deployment.zip`

`deployment.zip` is the complete package used by the uploader:

```text
deployment.zip
  boot.py
  device_loader_main.py
  main.zip
```

Those files are installed on the ESP32 as:

```text
/boot.py     <- firmware/source/boot.py
/main.py     <- firmware/source/device_loader_main.py
/main.zip    <- generated application image
```

The actual TRelay-S3-Controller application `main.py` remains inside `/main.zip`. The writable `/main.py` is the permanent loader that verifies and mounts the application archive.

## Build and deploy in one command

The normal development workflow is:

```cmd
python firmware\tools\upload_controller_firmware.py COM3 --build
```

Replace `COM3` with the COM port assigned to your ESP32-S3.

This command:

1. Builds a new firmware version.
2. Creates `main.zip` and `deployment.zip`.
3. Interrupts the running application and recovers the MicroPython REPL.
4. Verifies raw `mpremote` access.
5. Uploads `/boot.py`, `/main.py`, and `/main.zip` to temporary filenames.
6. Computes SHA-256 hashes on both the host and the ESP32.
7. Activates the files only after the transferred copies verify successfully.
8. Resets the controller.

No separate first-deployment option is required; the bootstrap files are installed by default.

## Deploy an already-built package

If `firmware/dist/deployment.zip` already exists:

```cmd
python firmware\tools\upload_controller_firmware.py COM3
```

To upload a specific package, including one downloaded from a GitHub release:

```cmd
python firmware\tools\upload_controller_firmware.py COM3 --firmware path\to\deployment.zip
```

The uploader can also accept the inner `main.zip`, but a full `deployment.zip` is preferred because it carries the matching `boot.py` and loader.

## Build without uploading

```cmd
python firmware\tools\upload_controller_firmware.py --build-only
```

This creates and verifies the firmware package without modifying a connected device.

## Application-only update

If `/boot.py` and the device loader are already correct and you intentionally want to replace only `/main.zip`:

```cmd
python firmware\tools\upload_controller_firmware.py COM3 --skip-bootstrap
```

For normal development, omit this option so the deployment package remains self-consistent.

## Deploy without resetting

```cmd
python firmware\tools\upload_controller_firmware.py COM3 --no-reset
```

## Windows USB network configuration

When using the optional USB-NCM runtime, the controller uses:

```text
Controller: 172.31.77.1/24
Windows:    172.31.77.2/24
Gateway:    none
DNS:        none
```

From an Administrator PowerShell window, configure the Windows side with:

```powershell
.\firmware\tools\configure_controller_usb.ps1
```

To return the adapter to DHCP later:

```powershell
.\firmware\tools\restore_controller_usb_dhcp.ps1
```

Because the USB adapter has no gateway, it does not become the computer's Internet path.

## Firmware versioning

The application version is read from:

```text
firmware/tools/next_firmware_version.json
```

A successful build embeds the version, build date, file count, checksum scheme, and SHA-256 checksum in `firmware_info.json`.

The builder advances the patch version only after both the application image and deployment package have been successfully verified.

## Persistent device data

Normal firmware deployments do **not** overwrite:

```text
/config.json
/events.json
```

`/config.json` contains device configuration. `/events.json` contains scheduled events and the persistent event log.

This means application updates can be deployed without erasing the controller's configured Wi-Fi, relay names, schedules, or event history.

See [firmware/docs/EVENTS_AND_PERSISTENCE.md](firmware/docs/EVENTS_AND_PERSISTENCE.md).

## Web access

TRelay-S3-Controller runs the same HTTP server over the available network interfaces:

- Wi-Fi
- USB CDC-NCM, when supported by the installed MicroPython runtime

The controller prints the available Web UI addresses during startup. Open the reported address in a browser.

Useful endpoints include:

```text
/                 Main relay-control UI
/events           Event/schedule management
/setup            Device configuration
/api/status       Controller and network status
```

With the project's USB-NCM MicroPython runtime installed, the USB controller side is `172.31.77.1/24`. Wi-Fi addresses are assigned by the configured wireless network.

See [firmware/docs/HTTP_WIFI_AND_USB.md](firmware/docs/HTTP_WIFI_AND_USB.md) for networking details.

## Wiping the device filesystem

A destructive filesystem wipe helper is also provided:

```cmd
python firmware\tools\wipe_device.py COM3
```

Use this only when intentionally resetting the writable MicroPython filesystem. Normal firmware updates do not require a wipe.

## GitHub releases

Application firmware can also be built by GitHub Actions and published as versioned release assets.

See the repository's [Releases](https://github.com/mrmessagewriter/trelay-s3-controller/releases) page for published builds.

## More documentation

- [Architecture](firmware/docs/ARCHITECTURE.md)
- [Build and deployment](firmware/docs/BUILD_AND_DEPLOY.md)
- [Events and persistence](firmware/docs/EVENTS_AND_PERSISTENCE.md)
- [Hardware](firmware/docs/HARDWARE.md)
- [HTTP, Wi-Fi, and USB](firmware/docs/HTTP_WIFI_AND_USB.md)
- [MicroPython USB-NCM runtime](firmware/docs/MICROPYTHON_USB_NCM.md)
- [GitHub releases](firmware/docs/GITHUB_RELEASES.md)

## License

See [LICENSE](LICENSE).
