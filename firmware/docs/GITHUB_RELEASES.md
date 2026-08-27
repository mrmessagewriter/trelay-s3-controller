# GitHub Releases

TRelay-S3-Controller publishes two independent kinds of GitHub Releases.

## 1. Application firmware releases

Workflow:

```text
.github/workflows/build-firmware-release.yml
```

Application tags use the normal version namespace:

```text
v1.0.22
v1.0.23
...
```

Release title example:

```text
LilyGo T-Relay-S3 Controller Firmware v1.0.22
```

Release asset example:

```text
LilyGo-T-Relay-S3-Controller-Firmware-v1.0.22.zip
```

The release ZIP is the same self-contained deployment package produced locally and contains:

```text
boot.py
device_loader_main.py
main.zip
```

The MicroPython board runtime is deliberately **not** included in the application release.

Application versioning is controlled by:

```text
firmware/tools/next_firmware_version.json
```

The application build runs on `windows-latest`.

## 2. Custom MicroPython releases

Workflow:

```text
.github/workflows/build-micropython-release.yml
```

The runtime uses a separate tag namespace:

```text
micropython-LILYGO_T_RELAY_S3_NCM-v1.0.15
micropython-LILYGO_T_RELAY_S3_NCM-v1.0.16
...
```

Release title example:

```text
MicroPython LILYGO_T_RELAY_S3_NCM v1.0.15
```

Release asset example:

```text
LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT-v1.0.15.bin
```

This is a combined ESP32-S3 MicroPython image containing the bootloader, partition table, MicroPython runtime, Octal-PSRAM configuration, and optional USB CDC-NCM support.

Custom MicroPython versioning is independent from the application firmware and is controlled by:

```text
firmware/tools/next_micropython_version.json
```

The MicroPython build runs on `ubuntu-latest` because the ESP-IDF/MicroPython ESP32 toolchain is Linux-oriented.

## Independent triggers

Application releases are triggered by changes to:

```text
firmware/source/**
firmware/tools/build_firmware_deployment.py
```

Custom MicroPython releases are triggered by changes to:

```text
firmware/micropython/**
firmware/tools/build_micropython_ncm.py
```

Both workflows can also be started manually with `workflow_dispatch`.

Changing application source does not publish a new MicroPython release. Changing the MicroPython board/runtime definition does not publish a new application firmware release.

## GitHub permissions

Both release workflows need:

```yaml
permissions:
  contents: write
```

so the repository `GITHUB_TOKEN` can create tags/releases and commit the incremented version-counter file.
