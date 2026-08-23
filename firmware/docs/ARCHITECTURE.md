# Firmware Architecture

## Device filesystem

The writable device filesystem is intentionally small in responsibility:

```text
/
  main.py       Permanent firmware loader
  main.zip      Current application firmware image
  config.json   Persistent device configuration
  events.json   Persistent events and event log
```

The application firmware ZIP is mounted read-only at `/firmware`.

## Firmware image

`main.zip` is an uncompressed ZIP file. It contains:

```text
main.py
events.py
weather.py
config.json
firmware_info.json
lib/
  microdot.py
static/
  index.html
  setup.html
  events.html
```

`device_loader_main.py` is source-controlled but is deliberately excluded from
`main.zip`. During initial installation it is copied to the device as
`/main.py`.

## Firmware metadata

The build generates `firmware_info.json`. It records:

- Firmware name.
- Build date.
- Firmware version.
- Aggregate SHA-256 checksum.
- Checksum algorithm and scope.
- Number of files.
- ZIP compression mode.

The checksum covers every other file in the firmware image as one deterministic
aggregate checksum.

## Firmware source and runtime data

Source-controlled defaults live under `firmware/source/`.

The writable `/config.json` is initialized from the firmware's default
`config.json` only when a persistent configuration does not already exist.

`/events.json` is runtime data and is never part of a firmware image.

## Static files

When running from the mounted firmware image, static assets are read from:

```text
/firmware/static/
```

The application also tolerates `/static/` while running directly from the
writable filesystem for debugging.
