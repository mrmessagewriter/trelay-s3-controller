#!/usr/bin/env python3
"""
Build the Sprinklers1 custom MicroPython runtime with USB CDC-NCM.

The tool is designed to work:
- directly on Linux, including GitHub Actions Ubuntu runners;
- from Windows by re-launching itself inside WSL.

Repository layout:

    firmware/
      micropython/
        micropython_build.json
        boards/
          T_RELAY_S3_NCM/
      tools/
        build_micropython_ncm.py

Output:

    firmware/dist/micropython/T_RELAY_S3_NCM-SPIRAM_OCT.bin

First local Windows build:

    python firmware\\tools\\build_micropython_ncm.py --bootstrap

Subsequent local builds:

    python firmware\\tools\\build_micropython_ncm.py

GitHub Actions also invokes this tool with --bootstrap.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Prepare ESP-IDF/toolchains and clone dependencies if needed.",
    )

    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean the ESP32 MicroPython build first.",
    )

    parser.add_argument(
        "--work-dir",
        default=None,
        help=(
            "Build workspace. Defaults to "
            "~/.cache/sprinklers1-micropython-build."
        ),
    )

    parser.add_argument(
        "--inside-wsl",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    return parser.parse_args()


def run(command, cwd=None, env=None, capture=False):
    print(">", " ".join(str(x) for x in command), flush=True)

    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )


def capture(command, cwd=None):
    return run(
        command,
        cwd=cwd,
        capture=True,
    ).stdout.strip()


def get_repo_paths():
    tools_dir = Path(__file__).resolve().parent
    firmware_dir = tools_dir.parent
    repo_root = firmware_dir.parent

    return (
        repo_root,
        firmware_dir,
        firmware_dir / "micropython",
    )


def relaunch_under_wsl(args):
    if shutil.which("wsl.exe") is None:
        raise RuntimeError(
            "WSL is required for the ESP32 MicroPython build on Windows.\n"
            "Install it with:\n"
            "  wsl --install -d Ubuntu"
        )

    script_windows = str(Path(__file__).resolve())

    script_wsl = capture(
        [
            "wsl.exe",
            "wslpath",
            "-a",
            script_windows,
        ]
    )

    command = [
        "wsl.exe",
        "python3",
        script_wsl,
        "--inside-wsl",
    ]

    if args.bootstrap:
        command.append("--bootstrap")

    if args.clean:
        command.append("--clean")

    if args.work_dir:
        command.extend(
            [
                "--work-dir",
                args.work_dir,
            ]
        )

    print()
    print("Re-launching MicroPython build inside WSL...")

    return subprocess.call(command)


def require_command(name, hint):
    if shutil.which(name) is None:
        raise RuntimeError(
            "Required command '{}' was not found.\n{}".format(
                name,
                hint,
            )
        )


def load_build_config(custom_dir):
    config_path = custom_dir / "micropython_build.json"

    if not config_path.is_file():
        raise FileNotFoundError(
            "Missing MicroPython build config: {}".format(
                config_path
            )
        )

    return json.loads(
        config_path.read_text(
            encoding="utf-8"
        )
    )


def clone_repo(url, ref, destination, recursive=False):
    if not destination.exists():
        command = [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            ref,
        ]

        if recursive:
            command.append("--recursive")

        command.extend(
            [
                url,
                str(destination),
            ]
        )

        run(command)

        if recursive:
            # Make sure nested submodule commits are present even when they
            # are not the tip of a branch.
            run(
                [
                    "git",
                    "submodule",
                    "update",
                    "--init",
                    "--recursive",
                    "--filter=tree:0",
                ],
                cwd=destination,
            )

        return

    run(
        [
            "git",
            "fetch",
            "--depth",
            "1",
            "origin",
            ref,
        ],
        cwd=destination,
    )

    run(
        [
            "git",
            "checkout",
            "--detach",
            "FETCH_HEAD",
        ],
        cwd=destination,
    )

    if recursive:
        run(
            [
                "git",
                "submodule",
                "update",
                "--init",
                "--recursive",
                "--filter=tree:0",
            ],
            cwd=destination,
        )


def ensure_esp_idf(config, work_dir, bootstrap):
    idf_dir = work_dir / "esp-idf"

    if not idf_dir.exists():
        if not bootstrap:
            raise RuntimeError(
                "ESP-IDF has not been prepared yet.\n"
                "Run this tool once with --bootstrap."
            )

        clone_repo(
            config["esp_idf_repository"],
            config["esp_idf_ref"],
            idf_dir,
            recursive=True,
        )

    if bootstrap:
        # Ensure we are on the configured IDF revision.
        clone_repo(
            config["esp_idf_repository"],
            config["esp_idf_ref"],
            idf_dir,
            recursive=True,
        )

        print()
        print("Installing ESP-IDF toolchain for ESP32-S3...")

        run(
            [
                "bash",
                "./install.sh",
                "esp32s3",
            ],
            cwd=idf_dir,
        )

    if not (idf_dir / "export.sh").is_file():
        raise RuntimeError(
            "ESP-IDF is incomplete. Re-run with --bootstrap."
        )

    return idf_dir


def ensure_micropython(config, work_dir):
    micropython_dir = work_dir / "micropython"

    clone_repo(
        config["micropython_repository"],
        config["micropython_ref"],
        micropython_dir,
        recursive=True,
    )

    ncm_source = (
        micropython_dir
        / "extmod"
        / "network_usbd_ncm.c"
    )

    if not ncm_source.is_file():
        raise RuntimeError(
            "The selected MicroPython revision does not contain "
            "USB NCM support (extmod/network_usbd_ncm.c is missing)."
        )

    return micropython_dir


def install_custom_board(custom_dir, micropython_dir, board_name):
    source = (
        custom_dir
        / "boards"
        / board_name
    )

    destination = (
        micropython_dir
        / "ports"
        / "esp32"
        / "boards"
        / board_name
    )

    if not source.is_dir():
        raise FileNotFoundError(
            "Missing custom board definition: {}".format(
                source
            )
        )

    if destination.exists():
        shutil.rmtree(destination)

    shutil.copytree(
        source,
        destination,
    )

    print(
        "Installed custom MicroPython board:",
        destination,
    )


def idf_shell(idf_dir, cwd, command):
    shell_command = (
        "set -e; "
        'source "{}" >/dev/null; '
        "export IDF_COMPONENT_MANAGER=1; "
        "{}".format(
            idf_dir / "export.sh",
            command,
        )
    )

    run(
        [
            "bash",
            "-lc",
            shell_command,
        ],
        cwd=cwd,
    )


def find_firmware_bin(esp32_dir, board_name, variant):
    expected = (
        esp32_dir
        / "build-{}-{}".format(
            board_name,
            variant,
        )
        / "firmware.bin"
    )

    if expected.is_file():
        return expected

    candidates = [
        path
        for path in esp32_dir.glob(
            "build-*/firmware.bin"
        )
        if board_name in path.parent.name
    ]

    if len(candidates) == 1:
        return candidates[0]

    raise FileNotFoundError(
        "MicroPython build completed but firmware.bin "
        "could not be located."
    )


def main():
    args = parse_args()

    if os.name == "nt" and not args.inside_wsl:
        return relaunch_under_wsl(args)

    if platform.system() != "Linux":
        raise RuntimeError(
            "The custom ESP32 MicroPython build requires Linux or WSL."
        )

    require_command(
        "git",
        "Install git before building.",
    )
    require_command(
        "make",
        "Install build-essential before building.",
    )
    require_command(
        "cmake",
        "Install cmake before building.",
    )

    repo_root, firmware_dir, custom_dir = get_repo_paths()
    config = load_build_config(custom_dir)

    work_dir = (
        Path(args.work_dir).expanduser().resolve()
        if args.work_dir
        else (
            Path.home()
            / ".cache"
            / "sprinklers1-micropython-build"
        )
    )

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("========================================")
    print(" Sprinklers1 Custom MicroPython Build")
    print("========================================")
    print()
    print("Repository:      ", repo_root)
    print("Build workspace: ", work_dir)
    print("Board:           ", config["board"])
    print("Variant:         ", config["variant"])
    print("MicroPython ref: ", config["micropython_ref"])
    print("ESP-IDF ref:     ", config["esp_idf_ref"])

    idf_dir = ensure_esp_idf(
        config,
        work_dir,
        args.bootstrap,
    )

    micropython_dir = ensure_micropython(
        config,
        work_dir,
    )

    install_custom_board(
        custom_dir,
        micropython_dir,
        config["board"],
    )

    print()
    print("Building mpy-cross...")

    run(
        [
            "make",
            "-C",
            "mpy-cross",
        ],
        cwd=micropython_dir,
    )

    # MicroPython CI installs these into the active IDF Python environment.
    idf_shell(
        idf_dir,
        micropython_dir,
        "python -m pip install -q pyelftools ar",
    )

    esp32_dir = (
        micropython_dir
        / "ports"
        / "esp32"
    )

    board_args = (
        "BOARD={} BOARD_VARIANT={}".format(
            config["board"],
            config["variant"],
        )
    )

    if args.clean:
        print()
        print("Cleaning previous custom MicroPython build...")

        idf_shell(
            idf_dir,
            esp32_dir,
            "make {} clean".format(
                board_args
            ),
        )

    print()
    print("Preparing MicroPython ESP32 submodules...")

    idf_shell(
        idf_dir,
        esp32_dir,
        "make {} submodules".format(
            board_args
        ),
    )

    print()
    print("Building USB-NCM + Octal-PSRAM MicroPython...")

    # GitHub Actions logs should include the complete compiler/link command on
    # failure.  Local builds remain quieter unless CI is set.
    make_command = "make {}".format(board_args)
    if os.environ.get("CI"):
        make_command += " V=1"

    idf_shell(
        idf_dir,
        esp32_dir,
        make_command,
    )

    firmware_bin = find_firmware_bin(
        esp32_dir,
        config["board"],
        config["variant"],
    )

    output_dir = (
        firmware_dir
        / "dist"
        / "micropython"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        output_dir
        / config["output_filename"]
    )

    shutil.copyfile(
        firmware_bin,
        output_file,
    )

    print()
    print("Custom MicroPython build successful.")
    print("Output:", output_file)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print()
        print("========================================", file=sys.stderr)
        print(" MicroPython build command failed", file=sys.stderr)
        print("========================================", file=sys.stderr)
        print("Exit code:", exc.returncode, file=sys.stderr)
        print("Command:", " ".join(str(x) for x in exc.cmd), file=sys.stderr)
        print(
            "The compiler/CMake error is in the output immediately above this message.",
            file=sys.stderr,
        )
        raise SystemExit(exc.returncode)
