#!/usr/bin/env python3
"""Build the Sprinklers1 firmware image.

Repository layout expected by this tool:

    firmware/
      source/
        *.py
        config.json
        lib/
        static/
      tools/
        build_firmware_deployment.py
        next_firmware_version.json
      dist/
        main.zip                 # generated, not source

The generated main.zip is intentionally uncompressed (ZIP_STORED).
firmware_info.json is generated during the build and placed inside
main.zip. next_firmware_version.json is advanced only after a verified
successful build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

FIRMWARE_NAME = "Sprinklers1"
FIRMWARE_INFO = "firmware_info.json"
VERSION_FILE = "next_firmware_version.json"

REQUIRED_FILES = {
    "main.py",
    "events.py",
    "weather.py",
    "config.json",
    "static/index.html",
    "static/setup.html",
    "static/events.html",
    "lib/microdot.py",
}

# This file is device-side source, but it is the permanent loader installed
# as /main.py on the writable filesystem. It must not be packaged into
# /main.zip because the application itself also contains main.py.
EXCLUDED_SOURCE_FILES = {
    "device_loader_main.py",
}

CHECKSUM_SCHEME = (
    "SHA-256 over every archive file except firmware_info.json, sorted by "
    "archive path. For each file: UTF-8 path, NUL, decimal byte length, "
    "NUL, raw file bytes, NUL."
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--source",
        default=None,
        help=(
            "Firmware source directory. Defaults to ../source relative "
            "to this tool."
        ),
    )

    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output firmware ZIP. Defaults to ../dist/main.zip relative "
            "to this tool."
        ),
    )

    parser.add_argument(
        "--version-file",
        default=None,
        help=(
            "Version JSON file. Defaults to next_firmware_version.json "
            "next to this tool."
        ),
    )

    parser.add_argument(
        "--name",
        default=FIRMWARE_NAME,
        help=f"Firmware name (default: {FIRMWARE_NAME}).",
    )

    return parser.parse_args()


def validate_version(version):
    parts = version.split(".")

    if (
        len(parts) != 3
        or any(
            not part.isdigit()
            for part in parts
        )
    ):
        raise ValueError(
            "Version '{}' must use numeric "
            "MAJOR.MINOR.PATCH format.".format(
                version
            )
        )


def read_version(path):
    if not path.is_file():
        raise FileNotFoundError(
            "Missing version file: {}".format(
                path
            )
        )

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    version = str(
        data.get(
            "next_version",
            ""
        )
    ).strip()

    validate_version(
        version
    )

    return version


def increment_patch(version):
    major, minor, patch = (
        int(part)
        for part in version.split(".")
    )

    return "{}.{}.{}".format(
        major,
        minor,
        patch + 1
    )


def collect_firmware_files(source):
    files = {}

    for path in sorted(
        source.glob("*.py")
    ):
        if (
            path.name
            in EXCLUDED_SOURCE_FILES
        ):
            continue

        files[
            path.name
        ] = path.read_bytes()

    config = (
        source /
        "config.json"
    )

    if config.is_file():
        files[
            "config.json"
        ] = config.read_bytes()

    for dirname in (
        "static",
        "lib",
    ):
        base = (
            source /
            dirname
        )

        if not base.is_dir():
            continue

        for path in sorted(
            base.rglob("*")
        ):
            if not path.is_file():
                continue

            archive_name = (
                path.relative_to(
                    source
                ).as_posix()
            )

            files[
                archive_name
            ] = path.read_bytes()

    missing = sorted(
        REQUIRED_FILES.difference(
            files
        )
    )

    if missing:
        raise FileNotFoundError(
            "Required firmware files are missing:\n  "
            + "\n  ".join(
                missing
            )
        )

    files.pop(
        FIRMWARE_INFO,
        None
    )

    return files


def calculate_checksum(files):
    hasher = hashlib.sha256()

    for name in sorted(files):
        data = files[name]

        hasher.update(
            name.encode(
                "utf-8"
            )
        )

        hasher.update(
            b"\x00"
        )

        hasher.update(
            str(
                len(data)
            ).encode(
                "ascii"
            )
        )

        hasher.update(
            b"\x00"
        )

        hasher.update(
            data
        )

        hasher.update(
            b"\x00"
        )

    return hasher.hexdigest()


def write_zip(
    output,
    files,
    firmware_info,
):
    output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp = output.with_suffix(
        output.suffix
        + ".tmp"
    )

    if temp.exists():
        temp.unlink()

    build_dt = (
        datetime.now()
        .timetuple()[:6]
    )

    with zipfile.ZipFile(
        temp,
        "w",
        compression=zipfile.ZIP_STORED,
    ) as archive:

        for name in sorted(files):
            info = zipfile.ZipInfo(
                name,
                date_time=build_dt,
            )

            info.compress_type = (
                zipfile.ZIP_STORED
            )

            info.external_attr = (
                0o100644 << 16
            )

            archive.writestr(
                info,
                files[name],
            )

        info_bytes = (
            json.dumps(
                firmware_info,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode(
            "utf-8"
        )

        info = zipfile.ZipInfo(
            FIRMWARE_INFO,
            date_time=build_dt,
        )

        info.compress_type = (
            zipfile.ZIP_STORED
        )

        info.external_attr = (
            0o100644 << 16
        )

        archive.writestr(
            info,
            info_bytes,
        )

    temp.replace(
        output
    )


def verify_zip(
    output,
    expected_checksum,
):
    with zipfile.ZipFile(
        output,
        "r",
    ) as archive:

        infos = (
            archive.infolist()
        )

        for info in infos:
            if (
                info.compress_type
                != zipfile.ZIP_STORED
            ):
                raise ValueError(
                    "Compressed entry found: "
                    + info.filename
                )

        metadata = json.loads(
            archive.read(
                FIRMWARE_INFO
            ).decode(
                "utf-8"
            )
        )

        if (
            metadata.get(
                "checksum"
            )
            != expected_checksum
        ):
            raise ValueError(
                "firmware_info.json checksum "
                "does not match build"
            )

        files = {
            item.filename:
                archive.read(
                    item.filename
                )
            for item in infos
            if (
                not item.is_dir()
                and item.filename
                != FIRMWARE_INFO
            )
        }

        actual = calculate_checksum(
            files
        )

        if (
            actual
            != expected_checksum
        ):
            raise ValueError(
                "ZIP checksum verification failed: "
                "{} != {}".format(
                    actual,
                    expected_checksum
                )
            )


def update_next_version(
    version_path,
    current_version,
):
    next_version = increment_patch(
        current_version
    )

    version_path.write_text(
        json.dumps(
            {
                "next_version":
                    next_version
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return next_version


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

    source = (
        Path(
            args.source
        ).resolve()
        if args.source
        else (
            firmware_dir /
            "source"
        ).resolve()
    )

    output = (
        Path(
            args.output
        ).resolve()
        if args.output
        else (
            firmware_dir /
            "dist" /
            "main.zip"
        ).resolve()
    )

    version_path = (
        Path(
            args.version_file
        ).resolve()
        if args.version_file
        else (
            tools_dir /
            VERSION_FILE
        ).resolve()
    )

    try:
        version = read_version(
            version_path
        )

        files = collect_firmware_files(
            source
        )

        checksum = calculate_checksum(
            files
        )

        build_date = (
            datetime.now(
                timezone.utc
            )
            .isoformat(
                timespec="seconds"
            )
            .replace(
                "+00:00",
                "Z"
            )
        )

        firmware_info = {
            "name":
                args.name,

            "date":
                build_date,

            "version":
                version,

            "checksum_algorithm":
                "SHA-256",

            "checksum_scope":
                CHECKSUM_SCHEME,

            "checksum":
                checksum,

            "file_count":
                len(files),

            "archive_compression":
                "stored",
        }

        write_zip(
            output,
            files,
            firmware_info,
        )

        verify_zip(
            output,
            checksum,
        )

        next_version = (
            update_next_version(
                version_path,
                version,
            )
        )

        print()
        print(
            "Firmware build successful"
        )
        print(
            "  Name:       ",
            args.name
        )
        print(
            "  Version:    ",
            version
        )
        print(
            "  Build date: ",
            build_date
        )
        print(
            "  Files:      ",
            len(files)
        )
        print(
            "  SHA-256:    ",
            checksum
        )
        print(
            "  Output:     ",
            output
        )
        print(
            "  Next build: ",
            next_version
        )
        print(
            "  Compression: none "
            "(ZIP_STORED)"
        )

        return 0

    except Exception as exc:
        print(
            "Firmware build failed:",
            exc,
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
