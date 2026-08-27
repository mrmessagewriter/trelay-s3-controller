# MicroPython ESP-IDF Build Troubleshooting

The TRelay-S3-Controller custom MicroPython runtime currently follows the versions configured in:

```text
firmware/micropython/micropython_build.json
```

At present the ESP-IDF ref is:

```text
v5.5.2
```

The build helper checks out the configured MicroPython and ESP-IDF revisions and resets dependency checkouts before building so files modified by an earlier failed build do not contaminate the next run.

## Build command

From the repository root:

```cmd
python firmware\tools\build_micropython_ncm.py --bootstrap --clean
```

On Windows the script relaunches inside WSL. The initial `--bootstrap` build installs the ESP-IDF toolchain; subsequent builds can normally omit it.

## CI diagnostics

If a custom MicroPython build fails, `build_micropython_ncm.py` reports failures from the ESP-IDF/Ninja build where possible.

The GitHub Action also prints the relevant build-log tail and uploads temporary failure diagnostics under a name similar to:

```text
micropython-LILYGO_T_RELAY_S3_NCM-failure-diagnostics
```

The diagnostic artifact is useful when GitHub truncates long compiler or Ninja command output.

When debugging a failure, start with the first compiler, linker, CMake, or Ninja error rather than later cascading failures.
