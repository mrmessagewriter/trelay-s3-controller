# TRelay-S3-Controller Project Notes

This repository contains the application firmware, deployment tools, and optional custom MicroPython runtime for the LILYGO T-Relay ESP32-S3 six-relay board.

## Application firmware

The TRelay-S3-Controller application provides:

- six-relay control through the board's 74HC595 shift register;
- a Microdot web UI and REST API;
- scheduled relay events and persistent event logs;
- optional NTP and weather-aware event conditions;
- Wi-Fi networking;
- optional USB CDC-NCM networking when the custom runtime is installed.

Application builds create an uncompressed `main.zip` plus a self-contained `deployment.zip` containing:

```text
boot.py
device_loader_main.py
main.zip
```

The deployment tools install these as `/boot.py`, `/main.py`, and `/main.zip`. Persistent `/config.json` and `/events.json` are preserved during normal application updates.

## Optional MicroPython runtime

The custom MicroPython runtime is only required for USB network access. It uses the `LILYGO_T_RELAY_S3_NCM` board configuration with the `SPIRAM_OCT` variant.

The USB network is configured as a private point-to-point LAN:

```text
Controller: 172.31.77.1/24
Windows:    172.31.77.2/24
Gateway:    none
DNS:        none
```

The Windows helper scripts are:

```text
firmware/tools/configure_controller_usb.ps1
firmware/tools/restore_controller_usb_dhcp.ps1
```

## Independent version streams

Application firmware and the custom MicroPython runtime are released independently. Their next-version files are:

```text
firmware/tools/next_firmware_version.json
firmware/tools/next_micropython_version.json
```

See `README.md` and the files under `firmware/docs/` for build, deployment, networking, and hardware details.
