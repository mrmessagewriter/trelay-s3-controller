#!/usr/bin/env python3
"""Build and/or upload Sprinklers1 firmware.

Examples, from firmware/tools:

    python upload_sprinkler_firmware.py COM3
    python upload_sprinkler_firmware.py COM3 --build
    python upload_sprinkler_firmware.py --build-only
    python upload_sprinkler_firmware.py COM3 --build --install-loader

The uploader replaces only /main.zip during a normal firmware update.
It does not overwrite /config.json or /events.json.
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

REMOTE_FIRMWARE = "/main.zip"
REMOTE_TEMP = "/main.zip.new"
REMOTE_LOADER = "/main.py"

FIRMWARE_INFO = "firmware_info.json"


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "port",
        nargs="?",
        default=DEFAULT_PORT,
        help=(
            "ESP32 serial port "
            "(default: {}).".format(
                DEFAULT_PORT
            )
        ),
    )

    parser.add_argument(
        "--build",
        action="store_true",
        help=(
            "Build a new firmware version "
            "before uploading."
        ),
    )

    parser.add_argument(
        "--build-only",
        action="store_true",
        help=(
            "Build a new firmware version "
            "without uploading."
        ),
    )

    parser.add_argument(
        "--install-loader",
        action="store_true",
        help=(
            "Also install source/"
            "device_loader_main.py "
            "as /main.py."
        ),
    )

    parser.add_argument(
        "--firmware",
        default=None,
        help=(
            "Firmware ZIP path. May be either the inner main.zip or a "
            "downloaded LilyGo T-Relay-S3 Controller Firmware release ZIP "
            "containing main.zip. Defaults to firmware/dist/main.zip."
        ),
    )

    parser.add_argument(
        "--no-reset",
        action="store_true",
        help=(
            "Do not reset the ESP32 "
            "after upload."
        ),
    )

    return parser.parse_args()


def run(
    command,
    capture=False,
):
    print(
        ">",
        " ".join(
            str(x)
            for x in command
        )
    )

    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=capture,
    )


def mpremote(
    port,
    *args
):
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
        [
            sys.executable,
            "-m",
            "mpremote",
            "--help",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if (
        result.returncode
        != 0
    ):
        raise RuntimeError(
            "mpremote is not installed. "
            "Install it with:\n"
            "  python -m pip install mpremote"
        )


def recover_repl(
    port,
    attempts=3,
):
    """Interrupt running firmware and obtain a normal MicroPython REPL."""

    try:
        import serial
    except ImportError as exc:
        raise RuntimeError(
            "pyserial is required for "
            "REPL recovery. Install it with:\n"
            "  python -m pip install pyserial"
        ) from exc

    print()
    print(
        "Preparing MicroPython REPL..."
    )

    last_response = b""

    for attempt in range(
        1,
        attempts + 1
    ):

        try:
            with serial.Serial(
                port=port,
                baudrate=115200,
                timeout=0.35,
                write_timeout=1.0,
            ) as connection:

                time.sleep(
                    0.20
                )

                try:
                    connection.reset_input_buffer()
                    connection.reset_output_buffer()
                except Exception:
                    pass

                connection.write(
                    b"\r\x03\x03\x02\r"
                )

                connection.flush()

                time.sleep(
                    0.35
                )

                response = (
                    connection.read(
                        1024
                    )
                )

                last_response = (
                    response
                )

                if (
                    b">>>"
                    in response
                ):
                    print(
                        "MicroPython REPL ready "
                        "(attempt {}).".format(
                            attempt
                        )
                    )
                    return

                connection.write(
                    b"\r"
                )

                connection.flush()

                time.sleep(
                    0.25
                )

                response += (
                    connection.read(
                        1024
                    )
                )

                last_response = (
                    response
                )

                if (
                    b">>>"
                    in response
                ):
                    print(
                        "MicroPython REPL ready "
                        "(attempt {}).".format(
                            attempt
                        )
                    )
                    return

        except Exception as exc:
            print(
                "  REPL recovery "
                "attempt {} failed:".format(
                    attempt
                ),
                exc,
            )

        time.sleep(
            0.35
        )

    raise RuntimeError(
        "COM port opened, but the device "
        "did not respond with a MicroPython "
        "REPL prompt.\n"
        "  Port: {}\n"
        "  Last response: {}\n\n"
        "Close Thonny/serial monitors, verify "
        "the COM port, press RESET once, "
        "and retry.".format(
            port,
            repr(
                last_response[
                    -200:
                ]
            ),
        )
    )


def verify_mpremote_repl(
    port
):
    print()
    print(
        "Verifying mpremote raw "
        "REPL access..."
    )

    result = subprocess.run(
        mpremote(
            port,
            "exec",
            "print('MPREMOTE_REPL_OK')",
        ),
        text=True,
        capture_output=True,
    )

    if (
        result.returncode == 0
        and
        "MPREMOTE_REPL_OK"
        in result.stdout
    ):
        print(
            "mpremote raw REPL "
            "access verified."
        )
        return

    detail = (
        result.stderr.strip()
        or
        result.stdout.strip()
        or
        "no response"
    )

    raise RuntimeError(
        "mpremote could not enter "
        "raw REPL.\n{}".format(
            detail
        )
    )


def _verify_stored_entries(
    archive,
    description,
):
    infos = archive.infolist()

    if not infos:
        raise ValueError(
            "{} is empty.".format(
                description
            )
        )

    for info in infos:
        if (
            info.compress_type
            != zipfile.ZIP_STORED
        ):
            raise ValueError(
                "{} must be uncompressed. "
                "Compressed entry: {}".format(
                    description,
                    info.filename,
                )
            )


def _read_firmware_metadata_from_archive(
    archive,
):
    if (
        FIRMWARE_INFO
        not in archive.namelist()
    ):
        raise ValueError(
            "firmware_info.json is "
            "missing from firmware ZIP."
        )

    return json.loads(
        archive.read(
            FIRMWARE_INFO
        ).decode(
            "utf-8"
        )
    )


def prepare_firmware_package(
    firmware_path,
    extraction_dir,
):
    """Accept either main.zip or a downloaded release package.

    Returns:
        metadata,
        upload_path,
        embedded_loader_path,
        input_kind
    """

    if not firmware_path.is_file():
        raise FileNotFoundError(
            "Firmware ZIP not found: {}\n"
            "Use --build to create it first.".format(
                firmware_path
            )
        )

    with zipfile.ZipFile(
        firmware_path,
        "r",
    ) as outer:

        _verify_stored_entries(
            outer,
            "Firmware ZIP",
        )

        names = set(
            outer.namelist()
        )

        # ----------------------------------------------------
        # Direct device firmware image:
        #
        #   main.zip
        #     firmware_info.json
        #     main.py
        #     ...
        # ----------------------------------------------------
        if FIRMWARE_INFO in names:
            metadata = (
                _read_firmware_metadata_from_archive(
                    outer
                )
            )

            return (
                metadata,
                firmware_path,
                None,
                "device firmware ZIP",
            )

        # ----------------------------------------------------
        # GitHub release package:
        #
        #   LilyGo-T-Relay-S3-Controller-Firmware-vX.Y.Z.zip
        #     device_loader_main.py
        #     main.zip
        # ----------------------------------------------------
        if "main.zip" not in names:
            raise ValueError(
                "ZIP is neither a device firmware image nor a "
                "LilyGo T-Relay-S3 Controller Firmware release package. "
                "Expected firmware_info.json or main.zip at the ZIP root."
            )

        main_zip_bytes = outer.read(
            "main.zip"
        )

        with zipfile.ZipFile(
            io.BytesIO(
                main_zip_bytes
            ),
            "r",
        ) as inner:

            _verify_stored_entries(
                inner,
                "Embedded main.zip",
            )

            metadata = (
                _read_firmware_metadata_from_archive(
                    inner
                )
            )

        extraction_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        extracted_firmware = (
            extraction_dir /
            "main.zip"
        )

        extracted_firmware.write_bytes(
            main_zip_bytes
        )

        embedded_loader = None

        if "device_loader_main.py" in names:
            embedded_loader = (
                extraction_dir /
                "device_loader_main.py"
            )

            embedded_loader.write_bytes(
                outer.read(
                    "device_loader_main.py"
                )
            )

        return (
            metadata,
            extracted_firmware,
            embedded_loader,
            "release package",
        )



def sha256_file(
    path
):
    hasher = hashlib.sha256()

    with path.open(
        "rb"
    ) as handle:
        while True:
            block = handle.read(
                65536
            )

            if not block:
                break

            hasher.update(
                block
            )

    return hasher.hexdigest()


def remove_remote_if_present(
    port,
    remote_path,
):
    code = (
        "import os\n"
        "p={!r}\n"
        "try:\n"
        " os.remove(p)\n"
        "except OSError:\n"
        " pass\n"
    ).format(
        remote_path
    )

    run(
        mpremote(
            port,
            "exec",
            code,
        )
    )


def remote_sha256(
    port,
    remote_path,
):
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
        "print(binascii.hexlify("
        "h.digest()).decode())\n"
    ).format(
        remote_path
    )

    result = run(
        mpremote(
            port,
            "exec",
            code,
        ),
        capture=True,
    )

    lines = (
        result.stdout
        .strip()
        .splitlines()
    )

    if not lines:
        raise RuntimeError(
            "Device did not return "
            "a SHA-256 checksum."
        )

    return (
        lines[-1]
        .strip()
        .lower()
    )


def install_loader(
    port,
    loader_path,
):
    if not loader_path.is_file():
        raise FileNotFoundError(
            "Missing device loader: "
            + str(
                loader_path
            )
        )

    print()
    print(
        "Installing permanent "
        "ZIP loader..."
    )

    run(
        mpremote(
            port,
            "fs",
            "cp",
            str(
                loader_path
            ),
            ":"
            + REMOTE_LOADER,
        )
    )


def upload_firmware(
    port,
    firmware_path,
):
    local_hash = sha256_file(
        firmware_path
    )

    print()
    print(
        "Uploading firmware to "
        "temporary device path..."
    )

    remove_remote_if_present(
        port,
        REMOTE_TEMP,
    )

    run(
        mpremote(
            port,
            "fs",
            "cp",
            str(
                firmware_path
            ),
            ":"
            + REMOTE_TEMP,
        )
    )

    print()
    print(
        "Verifying transferred "
        "firmware..."
    )

    device_hash = remote_sha256(
        port,
        REMOTE_TEMP,
    )

    if (
        device_hash
        != local_hash
    ):
        remove_remote_if_present(
            port,
            REMOTE_TEMP,
        )

        raise RuntimeError(
            "Firmware transfer verification "
            "failed.\n"
            "  Local SHA-256:  {}\n"
            "  Device SHA-256: {}".format(
                local_hash,
                device_hash
            )
        )

    print(
        "Transfer SHA-256 verified:",
        local_hash,
    )

    print()
    print(
        "Activating new firmware..."
    )

    activation_code = (
        "import os\n"
        "new={!r}\n"
        "current={!r}\n"
        "try:\n"
        " os.remove(current)\n"
        "except OSError:\n"
        " pass\n"
        "os.rename(new,current)\n"
        "print('Firmware activated:',"
        "current)\n"
    ).format(
        REMOTE_TEMP,
        REMOTE_FIRMWARE,
    )

    run(
        mpremote(
            port,
            "exec",
            activation_code,
        )
    )


def build_firmware(
    builder_path
):
    if not builder_path.is_file():
        raise FileNotFoundError(
            "Missing firmware builder: "
            + str(
                builder_path
            )
        )

    run(
        [
            sys.executable,
            str(
                builder_path
            ),
        ]
    )


def main():
    args = parse_args()

    tools_dir = (
        Path(__file__)
        .resolve()
        .parent
    )

    firmware_dir = (
        tools_dir.parent
    )

    builder_path = (
        tools_dir /
        "build_firmware_deployment.py"
    )

    repository_loader_path = (
        firmware_dir /
        "source" /
        "device_loader_main.py"
    )

    firmware_input_path = (
        Path(
            args.firmware
        ).resolve()
        if args.firmware
        else (
            firmware_dir /
            "dist" /
            "main.zip"
        ).resolve()
    )

    try:
        if (
            args.build
            or
            args.build_only
        ):
            print()
            print(
                "Building new firmware..."
            )

            build_firmware(
                builder_path
            )

            # A local build always produces the direct inner image.
            firmware_input_path = (
                firmware_dir /
                "dist" /
                "main.zip"
            ).resolve()

        with tempfile.TemporaryDirectory(
            prefix="lilygo-t-relay-firmware-"
        ) as temp_name:

            temp_dir = Path(
                temp_name
            )

            (
                metadata,
                upload_path,
                embedded_loader_path,
                input_kind,
            ) = prepare_firmware_package(
                firmware_input_path,
                temp_dir,
            )

            print()
            print(
                "Firmware image"
            )
            print(
                "  Name:       ",
                metadata.get(
                    "name",
                    "unknown"
                )
            )
            print(
                "  Version:    ",
                metadata.get(
                    "version",
                    "unknown"
                )
            )
            print(
                "  Build date: ",
                metadata.get(
                    "date",
                    "unknown"
                )
            )
            print(
                "  Input:      ",
                firmware_input_path
            )
            print(
                "  Input type: ",
                input_kind
            )

            if (
                upload_path
                != firmware_input_path
            ):
                print(
                    "  Device ZIP: ",
                    upload_path
                )

            if args.build_only:
                print()
                print(
                    "Build complete; "
                    "device was not modified."
                )
                return 0

            ensure_mpremote()

            print()
            print(
                "Target device:",
                args.port
            )

            recover_repl(
                args.port
            )

            verify_mpremote_repl(
                args.port
            )

            if args.install_loader:
                loader_path = (
                    embedded_loader_path
                    if embedded_loader_path
                    is not None
                    else repository_loader_path
                )

                if (
                    embedded_loader_path
                    is not None
                ):
                    print()
                    print(
                        "Using loader embedded "
                        "in release package."
                    )

                install_loader(
                    args.port,
                    loader_path
                )

            # Always upload the actual inner main.zip.
            # Never upload the outer GitHub release package to /main.zip.
            upload_firmware(
                args.port,
                upload_path
            )

            if not args.no_reset:
                print()
                print(
                    "Resetting device..."
                )

                run(
                    mpremote(
                        args.port,
                        "reset",
                    )
                )

            print()
            print(
                "Firmware deployment "
                "successful."
            )
            print(
                "  Version:",
                metadata.get(
                    "version",
                    "unknown"
                )
            )
            print(
                "  Device:",
                args.port
            )
            print(
                "  /config.json preserved"
            )
            print(
                "  /events.json preserved"
            )

            return 0

    except subprocess.CalledProcessError as exc:
        print(
            "\nFirmware deployment failed: "
            "command returned {}".format(
                exc.returncode
            ),
            file=sys.stderr,
        )

        if exc.stdout:
            print(
                exc.stdout,
                file=sys.stderr,
            )

        if exc.stderr:
            print(
                exc.stderr,
                file=sys.stderr,
            )

        return 1

    except Exception as exc:
        print(
            "\nFirmware deployment failed:",
            exc,
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
