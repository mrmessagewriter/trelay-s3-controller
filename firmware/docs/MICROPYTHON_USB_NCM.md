# Custom MicroPython USB-NCM Runtime

The Sprinklers1 custom MicroPython runtime is released independently from the
Sprinklers1 application firmware.

## Release identity

Custom MicroPython uses its own version stream:

```text
firmware/tools/next_micropython_version.json
```

Example:

```json
{
  "next_version": "1.0.0"
}
```

Git tags use the prefix:

```text
micropython-v
```

For example:

```text
micropython-v1.0.0
```

The release asset is a directly flashable combined ESP32-S3 binary:

```text
T_RELAY_S3_NCM-SPIRAM_OCT-v1.0.0.bin
```

## Application releases are separate

The MicroPython binary is not placed inside:

```text
Sprinklers1-vX.Y.Z.zip
```

Application firmware and the MicroPython runtime can therefore evolve at
different rates.

A user normally installs the custom MicroPython runtime only when:

- Setting up the device for the first time.
- USB-NCM support changes.
- The MicroPython base revision changes.
- ESP-IDF or board-level runtime configuration changes.

Normal Sprinklers1 application updates require only the application firmware
release.
## ESP32 DHCP integration

`network.USBD_NCM` enables its small DHCP server by default so the host gets an
address automatically.  The shared implementation lives in:

```text
shared/netutils/dhcpserver.c
```

The current ESP32 port does not include that source in its normal source list,
so the `T_RELAY_S3_NCM` board definition adds it through `MICROPY_SOURCE_BOARD`.
Without this addition, an NCM-enabled ESP32 build can reach the final build/link
stage and then fail because the DHCP server symbols are missing.

