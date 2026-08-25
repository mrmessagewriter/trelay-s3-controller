# GitHub Releases

Sprinklers1 publishes two independent kinds of GitHub Releases.

## 1. Application firmware releases

Workflow:

```text
.github/workflows/build-firmware-release.yml
```

Tags:

```text
v1.0.5
v1.0.6
...
```

Release title example:

```text
Sprinklers1 firmware v1.0.5
```

Release asset example:

```text
Sprinklers1-v1.0.5.zip
```

The outer ZIP contains exactly:

```text
device_loader_main.py
main.zip
```

The MicroPython board runtime is deliberately **not** included.

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

Tags use a separate namespace:

```text
micropython-v1.0.0
micropython-v1.0.1
...
```

Release title example:

```text
Sprinklers1 MicroPython board runtime v1.0.0
```

Release asset example:

```text
LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT-v1.0.0.bin
```

This is a combined ESP32-S3 MicroPython image containing the bootloader,
partition table, MicroPython runtime, Octal-PSRAM configuration, and USB
CDC-NCM support.

Custom MicroPython versioning is independent of application firmware and is
controlled by:

```text
firmware/tools/next_micropython_version.json
```

The MicroPython build runs on `ubuntu-latest` because the ESP-IDF/MicroPython
ESP32 toolchain is Linux-oriented.

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

Changing the application source does not publish a new MicroPython release.
Changing the MicroPython board/runtime definition does not publish a new
application firmware release.

## GitHub permissions

Both release workflows need:

```yaml
permissions:
  contents: write
```

so the repository `GITHUB_TOKEN` can create tags/releases and commit the
incremented version-counter file.

If branch protection prevents `github-actions[bot]` from pushing to `main`,
either allow that version-counter update or change the version-bump step to a
pull-request workflow.
