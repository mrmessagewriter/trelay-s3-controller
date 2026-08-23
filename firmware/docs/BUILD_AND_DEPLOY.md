# Build and Deployment

## Requirements

On the host computer:

```cmd
python -m pip install mpremote pyserial
```

The ESP32-S3 should run the MicroPython `SPIRAM_OCT` build so the board's Octal
PSRAM is available.

## Build firmware

From the repository root:

```cmd
python firmware\tools\build_firmware_deployment.py
```

The builder reads:

```text
firmware/source/
```

and generates:

```text
firmware/dist/main.zip
```

The ZIP uses `ZIP_STORED`; files are not compressed.

The builder also creates `firmware_info.json` inside the ZIP and increments:

```text
firmware/tools/next_firmware_version.json
```

only after the image has been successfully verified.

## Upload existing firmware

```cmd
python firmware\tools\upload_sprinkler_firmware.py COM3
```

## Build and upload in one step

```cmd
python firmware\tools\upload_sprinkler_firmware.py COM3 --build
```

## First deployment

The first deployment also installs the permanent ZIP loader:

```cmd
python firmware\tools\upload_sprinkler_firmware.py COM3 --build --install-loader
```

This copies:

```text
firmware/source/device_loader_main.py
```

to:

```text
/main.py
```

## Update safety

The uploader:

1. Interrupts the running application and recovers the MicroPython REPL.
2. Uploads the new image as `/main.zip.new`.
3. Calculates SHA-256 on the transferred file.
4. Compares that value to the host file.
5. Replaces `/main.zip` only after successful transfer verification.
6. Resets the device unless `--no-reset` was specified.

Normal updates do not overwrite:

```text
/config.json
/events.json
```

## Build only

```cmd
python firmware\tools\upload_sprinkler_firmware.py --build-only
```

## Wipe writable filesystem

```cmd
python firmware\tools\wipe_device.py COM3
```

The wipe utility runs destructive code only after it detects MicroPython on the
device. The host-side invocation does not delete host files.
