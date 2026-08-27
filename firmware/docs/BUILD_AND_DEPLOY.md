# Build and Deployment

## Requirements

On the host computer:

```cmd
python -m pip install mpremote pyserial
```

A compatible MicroPython runtime must already be installed on the ESP32-S3. The custom `LILYGO_T_RELAY_S3_NCM` runtime in this repository is only required when USB CDC-NCM networking is desired.

## Build application firmware

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
firmware/dist/deployment.zip
```

`main.zip` contains the application and generated `firmware_info.json` manifest. `deployment.zip` contains:

```text
boot.py
device_loader_main.py
main.zip
```

Both ZIPs use `ZIP_STORED`; files are not compressed.

The application version comes from:

```text
firmware/tools/next_firmware_version.json
```

The next version is advanced only after the generated files have been successfully verified.

## Build and upload in one step

```cmd
python firmware\tools\upload_controller_firmware.py COM3 --build
```

Replace `COM3` with the device's serial port.

The bootstrap files are installed by default. The deployment places:

```text
boot.py               -> /boot.py
device_loader_main.py -> /main.py
main.zip               -> /main.zip
```

## Upload an existing deployment package

```cmd
python firmware\tools\upload_controller_firmware.py COM3
```

By default the uploader reads:

```text
firmware/dist/deployment.zip
```

A specific package can be selected with:

```cmd
python firmware\tools\upload_controller_firmware.py COM3 --firmware path\to\deployment.zip
```

## Application-only update

To intentionally update only `/main.zip` and leave `/boot.py` and the permanent loader unchanged:

```cmd
python firmware\tools\upload_controller_firmware.py COM3 --skip-bootstrap
```

For normal development, install the complete deployment package so all bootstrap files remain matched to the application.

## Build only

```cmd
python firmware\tools\upload_controller_firmware.py --build-only
```

## Deploy without resetting

```cmd
python firmware\tools\upload_controller_firmware.py COM3 --no-reset
```

## Update safety

The uploader:

1. Interrupts the running application and recovers the MicroPython REPL.
2. Stages new files under temporary names.
3. Calculates SHA-256 on each transferred file.
4. Compares the device checksum to the host checksum.
5. Activates the verified files only after successful transfer verification.
6. Resets the device unless `--no-reset` was specified.

Normal updates do not overwrite:

```text
/config.json
/events.json
```

## Optional USB network host configuration

When the custom USB-NCM runtime is installed, Windows can be configured for the point-to-point USB LAN with:

```powershell
.\firmware\tools\configure_controller_usb.ps1
```

The normal addresses are:

```text
Controller: 172.31.77.1/24
Windows:    172.31.77.2/24
```

To return the Windows adapter to DHCP:

```powershell
.\firmware\tools\restore_controller_usb_dhcp.ps1
```

## Wipe writable filesystem

```cmd
python firmware\tools\wipe_device.py COM3
```

The wipe utility runs destructive code only after it detects MicroPython on the device. It clears the writable MicroPython filesystem but does not erase the MicroPython runtime itself.
