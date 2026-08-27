#!/usr/bin/env python3
"""Build and/or upload TRelay-S3-Controller application firmware.

Examples, from the repository root:

    python firmware/tools/upload_controller_firmware.py COM3
    python firmware/tools/upload_controller_firmware.py COM3 --build
    python firmware/tools/upload_controller_firmware.py --build-only

The normal deployment installs:
    boot.py               -> /boot.py
    device_loader_main.py -> /main.py
    main.zip              -> /main.zip

/config.json and /events.json are preserved.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

DEFAULT_PORT = "COM3"
FIRMWARE_INFO = "firmware_info.json"
DEPLOYMENT_FILENAME = "deployment.zip"

REMOTE_BOOT = "/boot.py"
REMOTE_BOOT_TEMP = "/boot.py.new"
REMOTE_LOADER = "/main.py"
REMOTE_LOADER_TEMP = "/main.py.new"
REMOTE_FIRMWARE = "/main.zip"
REMOTE_FIRMWARE_TEMP = "/main.zip.new"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "port",
        nargs="?",
        default=DEFAULT_PORT,
        help="ESP32 serial port (default: {}).".format(DEFAULT_PORT),
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build a new application firmware version before uploading.",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Build and verify firmware without modifying a device.",
    )
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Upload only /main.zip; leave /boot.py and /main.py unchanged.",
    )
    parser.add_argument(
        "--firmware",
        default=None,
        help=(
            "Path to deployment.zip or main.zip. Defaults to "
            "firmware/dist/deployment.zip."
        ),
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Do not reset the ESP32 after a successful deployment.",
    )
    return parser.parse_args()


def run(command, capture=False):
    print(">", " ".join(str(part) for part in command))
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=capture,
    )


def mpremote(port, *args):
    return [
        sys.executable,
        "-m",
        "mpremote",
        "connect",
        port,
        *args,
    ]


def ensure_mpremote():
    result = subprocess.run(
        [sys.executable, "-m", "mpremote", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "mpremote is not installed. Install it with:\n"
            "  python -m pip install mpremote"
        )


def recover_repl(port, attempts=3):
    """Interrupt a running application and obtain the normal MicroPython REPL."""
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError(
            "pyserial is required. Install it with:\n"
            "  python -m pip install pyserial"
        ) from exc

    print("\nPreparing MicroPython REPL...")
    last_response = b""

    for attempt in range(1, attempts + 1):
        try:
            with serial.Serial(
                port=port,
                baudrate=115200,
                timeout=0.35,
                write_timeout=1.0,
            ) as connection:
                time.sleep(0.20)
                try:
                    connection.reset_input_buffer()
                    connection.reset_output_buffer()
                except Exception:
                    pass

                connection.write(b"\r\x03\x03\x02\r")
                connection.flush()
                time.sleep(0.35)
                response = connection.read(1024)
                last_response = response

                if b">>>" not in response:
                    connection.write(b"\r")
                    connection.flush()
                    time.sleep(0.25)
                    response += connection.read(1024)
                    last_response = response

                if b">>>" in response:
                    print("MicroPython REPL ready (attempt {}).".format(attempt))
                    return
        except Exception as exc:
            print("  REPL recovery attempt {} failed: {}".format(attempt, exc))

        time.sleep(0.35)

    raise RuntimeError(
        "COM port opened, but the device did not respond with a MicroPython "
        "REPL prompt.\n  Port: {}\n  Last response: {}\n\n"
        "Close Thonny/serial monitors, verify the COM port, press RESET once, "
        "and retry.".format(port, repr(last_response[-200:]))
    )


def verify_mpremote_repl(port):
    print("\nVerifying mpremote raw REPL access...")
    result = subprocess.run(
        mpremote(port, "exec", "print('MPREMOTE_REPL_OK')"),
        text=True,
        capture_output=True,
    )
    if result.returncode == 0 and "MPREMOTE_REPL_OK" in result.stdout:
        print("mpremote raw REPL access verified.")
        return

    detail = result.stderr.strip() or result.stdout.strip() or "no response"
    raise RuntimeError("mpremote could not enter raw REPL.\n{}".format(detail))


def verify_stored_entries(archive, description):
    infos = archive.infolist()
    if not infos:
        raise ValueError("{} is empty.".format(description))
    for info in infos:
        if info.compress_type != zipfile.ZIP_STORED:
            raise ValueError(
                "{} must be uncompressed. Compressed entry: {}".format(
                    description,
                    info.filename,
                )
            )


def read_metadata(archive):
    if FIRMWARE_INFO not in archive.namelist():
        raise ValueError("firmware_info.json is missing from main.zip.")
    return json.loads(archive.read(FIRMWARE_INFO).decode("utf-8"))


def prepare_package(firmware_path, extraction_dir):
    """Return metadata, main.zip, optional boot.py, optional loader, and type."""
    if not firmware_path.is_file():
        raise FileNotFoundError(
            "Firmware ZIP not found: {}\nUse --build to create it first.".format(
                firmware_path
            )
        )

    with zipfile.ZipFile(firmware_path, "r") as outer:
        verify_stored_entries(outer, "Firmware ZIP")
        names = set(outer.namelist())

        if FIRMWARE_INFO in names:
            return (
                read_metadata(outer),
                firmware_path,
                None,
                None,
                "device firmware ZIP",
            )

        if "main.zip" not in names:
            raise ValueError(
                "ZIP is neither a main.zip application image nor a "
                "TRelay-S3-Controller deployment package."
            )

        main_bytes = outer.read("main.zip")
        with zipfile.ZipFile(io.BytesIO(main_bytes), "r") as inner:
            verify_stored_entries(inner, "Embedded main.zip")
            metadata = read_metadata(inner)

        extraction_dir.mkdir(parents=True, exist_ok=True)
        main_path = extraction_dir / "main.zip"
        main_path.write_bytes(main_bytes)

        boot_path = None
        if "boot.py" in names:
            boot_path = extraction_dir / "boot.py"
            boot_path.write_bytes(outer.read("boot.py"))

        loader_path = None
        if "device_loader_main.py" in names:
            loader_path = extraction_dir / "device_loader_main.py"
            loader_path.write_bytes(outer.read("device_loader_main.py"))

        return metadata, main_path, boot_path, loader_path, "deployment package"


def sha256_file(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(65536)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def remove_remote_if_present(port, remote_path):
    code = (
        "import os\n"
        "p={!r}\n"
        "try:\n"
        " os.remove(p)\n"
        "except OSError:\n"
        " pass\n"
    ).format(remote_path)
    run(mpremote(port, "exec", code))


def remote_sha256(port, remote_path):
    code = (
        "import hashlib,binascii\n"
        "p={!r}\n"
        "h=hashlib.sha256()\n"
        "f=open(p,'rb')\n"
        "while True:\n"
        " b=f.read(4096)\n"
        " if not b: break\n"
        " h.update(b)\n"
        "f.close()\n"
        "print(binascii.hexlify(h.digest()).decode())\n"
    ).format(remote_path)
    result = run(mpremote(port, "exec", code), capture=True)
    lines = result.stdout.strip().splitlines()
    if not lines:
        raise RuntimeError("Device did not return a SHA-256 checksum.")
    return lines[-1].strip().lower()


def stage_verified_file(port, local_path, remote_temp, label):
    if local_path is None or not local_path.is_file():
        raise FileNotFoundError("Missing {}: {}".format(label, local_path))

    local_hash = sha256_file(local_path)
    print("\nStaging {}...".format(label))
    remove_remote_if_present(port, remote_temp)
    run(mpremote(port, "fs", "cp", str(local_path), ":" + remote_temp))

    device_hash = remote_sha256(port, remote_temp)
    if device_hash != local_hash:
        remove_remote_if_present(port, remote_temp)
        raise RuntimeError(
            "{} transfer verification failed.\n"
            "  Local SHA-256:  {}\n"
            "  Device SHA-256: {}".format(label, local_hash, device_hash)
        )

    print("{} SHA-256 verified: {}".format(label, local_hash))


def activate_deployment(port, staged_items):
    lines = [
        "import os",
        "def rm(p):",
        " try:",
        "  os.remove(p)",
        " except OSError:",
        "  pass",
    ]

    for remote_temp, remote_current in staged_items:
        lines.extend(
            [
                "rm({!r})".format(remote_current + ".bak"),
                "try:",
                " os.rename({!r},{!r})".format(
                    remote_current,
                    remote_current + ".bak",
                ),
                "except OSError:",
                " pass",
                "os.rename({!r},{!r})".format(remote_temp, remote_current),
            ]
        )

    for _, remote_current in staged_items:
        lines.append("rm({!r})".format(remote_current + ".bak"))

    lines.append("print('Deployment activated')")
    run(mpremote(port, "exec", "\n".join(lines) + "\n"))


def upload_deployment(port, firmware_path, boot_path, loader_path, include_bootstrap):
    staged = []

    if include_bootstrap:
        stage_verified_file(port, boot_path, REMOTE_BOOT_TEMP, "boot.py")
        staged.append((REMOTE_BOOT_TEMP, REMOTE_BOOT))

        stage_verified_file(
            port,
            loader_path,
            REMOTE_LOADER_TEMP,
            "device loader (/main.py)",
        )
        staged.append((REMOTE_LOADER_TEMP, REMOTE_LOADER))

    stage_verified_file(
        port,
        firmware_path,
        REMOTE_FIRMWARE_TEMP,
        "application firmware (/main.zip)",
    )
    staged.append((REMOTE_FIRMWARE_TEMP, REMOTE_FIRMWARE))

    print("\nActivating verified deployment...")
    activate_deployment(port, staged)


def build_firmware(builder_path):
    if not builder_path.is_file():
        raise FileNotFoundError("Missing firmware builder: {}".format(builder_path))
    run([sys.executable, str(builder_path)])


def main():
    args = parse_args()
    tools_dir = Path(__file__).resolve().parent
    firmware_dir = tools_dir.parent
    builder_path = tools_dir / "build_firmware_deployment.py"
    repository_boot = firmware_dir / "source" / "boot.py"
    repository_loader = firmware_dir / "source" / "device_loader_main.py"

    firmware_input = (
        Path(args.firmware).resolve()
        if args.firmware
        else (firmware_dir / "dist" / DEPLOYMENT_FILENAME).resolve()
    )

    try:
        if args.build or args.build_only:
            print("\nBuilding new firmware...")
            build_firmware(builder_path)
            firmware_input = (firmware_dir / "dist" / DEPLOYMENT_FILENAME).resolve()

        with tempfile.TemporaryDirectory(prefix="trelay-s3-controller-") as temp_name:
            temp_dir = Path(temp_name)
            metadata, main_zip, embedded_boot, embedded_loader, input_kind = (
                prepare_package(firmware_input, temp_dir)
            )

            print("\nFirmware image")
            print("  Name:       ", metadata.get("name", "unknown"))
            print("  Version:    ", metadata.get("version", "unknown"))
            print("  Build date: ", metadata.get("date", "unknown"))
            print("  Input:      ", firmware_input)
            print("  Input type: ", input_kind)

            if args.build_only:
                print("\nBuild complete; device was not modified.")
                return 0

            ensure_mpremote()
            print("\nTarget device:", args.port)
            recover_repl(args.port)
            verify_mpremote_repl(args.port)

            include_bootstrap = not args.skip_bootstrap
            boot_path = embedded_boot or repository_boot
            loader_path = embedded_loader or repository_loader

            upload_deployment(
                args.port,
                main_zip,
                boot_path,
                loader_path,
                include_bootstrap,
            )

            if not args.no_reset:
                print("\nResetting device...")
                run(mpremote(args.port, "reset"))

            print("\nFirmware deployment successful.")
            print("  Version:", metadata.get("version", "unknown"))
            print("  Device:", args.port)
            if include_bootstrap:
                print("  /boot.py installed")
                print("  /main.py loader installed")
            print("  /main.zip installed")
            print("  /config.json preserved")
            print("  /events.json preserved")
            return 0

    except subprocess.CalledProcessError as exc:
        print(
            "\nFirmware deployment failed: command returned {}".format(
                exc.returncode
            ),
            file=sys.stderr,
        )
        if exc.stdout:
            print(exc.stdout, file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return 1
    except Exception as exc:
        print("\nFirmware deployment failed:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
