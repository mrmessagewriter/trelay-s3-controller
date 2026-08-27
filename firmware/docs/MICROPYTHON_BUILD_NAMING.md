# MicroPython Build Naming

The custom MicroPython runtime uses a MicroPython-style board identity rather than the TRelay-S3-Controller application name.

## Board name

```text
LILYGO_T_RELAY_S3_NCM
```

This follows the same vendor/board naming style as MicroPython's existing LILYGO board names such as `LILYGO_T3_S3`.

## Variant

```text
SPIRAM_OCT
```

## Local build output

```text
firmware/dist/micropython/LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT.bin
```

## GitHub release identity

The GitHub Action is displayed as:

```text
Build and Publish MicroPython LILYGO_T_RELAY_S3_NCM
```

Example release asset:

```text
LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT-v1.0.0.bin
```

Example tag:

```text
micropython-LILYGO_T_RELAY_S3_NCM-v1.0.0
```

The `TRelay-S3-Controller` name identifies the application firmware. `LILYGO_T_RELAY_S3_NCM` identifies the optional custom MicroPython runtime and remains deliberately separate.

## Repository board directory

The custom board definition lives at:

```text
firmware/micropython/boards/LILYGO_T_RELAY_S3_NCM
```
