#!/usr/bin/env python3
"""
Safely wipe the MicroPython filesystem on an ESP32.

Host usage:

    python wipe_device.py COM3

or, to skip the confirmation prompt:

    python wipe_device.py COM3 --yes

Behavior:
- When run under normal desktop Python, this script NEVER deletes files.
  It launches itself on the ESP32 using mpremote.
- When run under MicroPython, it deletes the contents of the device's "/"
  filesystem.
- The MicroPython firmware itself is NOT erased.
"""

import sys


def running_on_micropython():
    try:
        return sys.implementation.name == "micropython"
    except Exception:
        return False


# ============================================================
# DEVICE MODE
# ============================================================

def wipe_micropython_filesystem():
    """
    This function is only called when running under MicroPython.
    """

    if not running_on_micropython():
        raise RuntimeError(
            "REFUSING TO WIPE: this code is not running under MicroPython."
        )

    import os

    def remove_tree(path):
        try:
            names = os.listdir(path)
        except OSError:
            # Not a directory.
            os.remove(path)
            return

        for name in names:
            if name in (".", ".."):
                continue

            if path == "/":
                child = "/" + name
            else:
                child = path.rstrip("/") + "/" + name

            try:
                # Try treating it as a file first.
                os.remove(child)

            except OSError:
                # If remove failed, treat it as a directory.
                remove_tree(child)

                try:
                    os.rmdir(child)
                except OSError as exc:
                    print(
                        "WARNING: could not remove directory:",
                        child,
                        repr(exc),
                    )

    print()
    print("========================================")
    print(" MicroPython device filesystem wipe")
    print("========================================")
    print()
    print("Platform:", sys.implementation.name)

    try:
        before = os.listdir("/")
    except Exception as exc:
        print("ERROR: unable to read device filesystem:", repr(exc))
        raise

    print("Files before wipe:")
    for name in before:
        print(" ", name)

    print()
    print("Wiping device filesystem...")

    remove_tree("/")

    remaining = os.listdir("/")

    print()
    print("Files remaining:")
    if remaining:
        for name in remaining:
            print(" ", name)
    else:
        print(" <none>")

    if remaining:
        raise RuntimeError(
            "Filesystem wipe was incomplete."
        )

    print()
    print("Filesystem successfully cleared.")
    print("MicroPython firmware was NOT erased.")


# ============================================================
# HOST MODE
# ============================================================

def run_on_device():
    """
    Desktop Python entry point.

    This code never deletes host files. It invokes this exact script on the
    ESP32 using:

        python -m mpremote connect <PORT> run wipe_device.py
    """

    import subprocess
    from pathlib import Path

    port = "COM3"
    assume_yes = False

    for arg in sys.argv[1:]:
        if arg == "--yes":
            assume_yes = True
        elif arg.startswith("-"):
            print("Unknown option:", arg)
            return 2
        else:
            port = arg

    script_path = Path(__file__).resolve()

    print()
    print("========================================")
    print(" ESP32 MicroPython filesystem wipe")
    print("========================================")
    print()
    print("Host Python detected.")
    print("No host files will be deleted.")
    print()
    print("Target device:", port)
    print("Script:", script_path)
    print()
    print("This will delete ALL files stored in the")
    print("MicroPython filesystem on the target ESP32.")
    print()
    print("It will NOT erase the MicroPython firmware.")
    print()

    if not assume_yes:
        answer = input(
            'Type WIPE to continue: '
        ).strip()

        if answer != "WIPE":
            print("Cancelled.")
            return 0

    # Verify mpremote is available before attempting anything.
    check = subprocess.run(
        [
            sys.executable,
            "-m",
            "mpremote",
            "--help",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if check.returncode != 0:
        print()
        print("ERROR: mpremote is not installed.")
        print()
        print("Install it with:")
        print("  python -m pip install mpremote")
        return 1

    command = [
        sys.executable,
        "-m",
        "mpremote",
        "connect",
        port,
        "run",
        str(script_path),
    ]

    print()
    print("Running wipe script on ESP32:")
    print(" ", " ".join(command))
    print()

    result = subprocess.run(command)

    if result.returncode != 0:
        print()
        print(
            "ERROR: device wipe failed with exit code",
            result.returncode,
        )
        return result.returncode

    print()
    print("Device wipe completed successfully.")

    # Verify the root directory separately.
    print()
    print("Verifying device filesystem...")

    verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "mpremote",
            "connect",
            port,
            "exec",
            "import os; print(os.listdir('/'))",
        ]
    )

    if verify.returncode != 0:
        print(
            "WARNING: wipe completed, but verification failed."
        )
        return verify.returncode

    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if running_on_micropython():
    wipe_micropython_filesystem()
else:
    raise SystemExit(
        run_on_device()
    )
