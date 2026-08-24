# MicroPython ESP-IDF Build Pin

The Sprinklers1 custom MicroPython runtime is currently pinned to:

```text
ESP-IDF v5.3
```

rather than ESP-IDF 5.5.x.

## Why

A GitHub Actions build using ESP-IDF 5.5.2 reached the managed
`espressif/mdns` component and failed while compiling `mdns.c` with the
ESP-IDF 5.5.2 Xtensa GCC 14.2 toolchain.

Current MicroPython documents ESP-IDF v5.3 as a supported ESP32 build version.
ESP-IDF v5.3 uses the earlier Xtensa GCC 13.x toolchain, so this pin avoids the
5.5.x/GCC-14 compiler path while we keep the newer MicroPython source needed for
`network.USBD_NCM`.

The version is controlled in:

```text
firmware/micropython/micropython_build.json
```

with:

```json
"esp_idf_ref": "v5.3"
```

## CI diagnostics

If a custom MicroPython build fails, `build_micropython_ncm.py` now scans the
ESP-IDF build log directory and prints the relevant `error:` / `fatal:` /
`undefined reference` lines plus the tail of the generated logs.

The GitHub Action also uploads those ESP-IDF logs as the temporary workflow
artifact:

```text
micropython-esp-idf-failure-logs
```

This makes the underlying compiler failure available even when GitHub truncates
the very long Ninja command output.
