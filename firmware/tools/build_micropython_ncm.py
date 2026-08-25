#!/usr/bin/env python3
"""
Build the LILYGO_T_RELAY_S3_NCM MicroPython runtime with USB CDC-NCM.

The tool is designed to work:
- directly on Linux, including GitHub Actions Ubuntu runners;
- from Windows by re-launching itself inside WSL.

Repository layout:

    firmware/
      micropython/
        micropython_build.json
        boards/
          LILYGO_T_RELAY_S3_NCM/
      tools/
        build_micropython_ncm.py

Output:

    firmware/dist/micropython/LILYGO_T_RELAY_S3_NCM-SPIRAM_OCT.bin

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
            "~/.cache/micropython-lilygo-t-relay-s3-ncm-build."
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

    # Builds can modify ESP-IDF component lockfiles.  Always restore the
    # checkout to the requested revision before applying our custom board.
    run(
        [
            "git",
            "reset",
            "--hard",
            "FETCH_HEAD",
        ],
        cwd=destination,
    )

    run(
        [
            "git",
            "clean",
            "-ffd",
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


def print_idf_failure_logs(esp32_dir, board_name, variant):
    """Print the useful tail of ESP-IDF's generated stdout/stderr logs."""

    build_dir = (
        esp32_dir
        / "build-{}-{}".format(
            board_name,
            variant,
        )
    )

    log_dir = build_dir / "log"

    if not log_dir.is_dir():
        print(
            "ESP-IDF log directory was not found:",
            log_dir,
            file=sys.stderr,
        )
        return

    # ESP-IDF writes logs in both the main build log directory and nested
    # directories such as build-.../submodules/log. Search recursively so a
    # failure in either phase is visible.
    log_files = sorted(
        list(build_dir.rglob("idf_py_stderr_output_*"))
        + list(build_dir.rglob("idf_py_stdout_output_*")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not log_files:
        print(
            "No ESP-IDF idf_py output logs were found under {}".format(
                build_dir
            ),
            file=sys.stderr,
        )
        return

    print()
    print(
        "========================================",
        file=sys.stderr,
    )
    print(
        " ESP-IDF diagnostic log tail",
        file=sys.stderr,
    )
    print(
        "========================================",
        file=sys.stderr,
    )

    for path in log_files[:4]:
        print()
        print(
            "--- {} ---".format(path.name),
            file=sys.stderr,
        )

        try:
            lines = path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except Exception as exc:
            print(
                "Unable to read {}: {}".format(
                    path,
                    exc,
                ),
                file=sys.stderr,
            )
            continue

        # First print compiler/error lines if present.
        interesting = [
            line
            for line in lines
            if (
                "error:" in line.lower()
                or "fatal:" in line.lower()
                or "undefined reference" in line.lower()
                or "ninja: build stopped" in line.lower()
            )
        ]

        if interesting:
            print(
                "Relevant error lines:",
                file=sys.stderr,
            )

            for line in interesting[-80:]:
                print(
                    line,
                    file=sys.stderr,
                )

        print(
            "Last 120 log lines:",
            file=sys.stderr,
        )

        for line in lines[-120:]:
            print(
                line,
                file=sys.stderr,
            )



def patch_tinyusb_ncm_descriptor_compat(micropython_dir, esp32_dir):
    """Adapt MicroPython's NCM descriptor call to the ESP32 TinyUSB fork.

    Current MicroPython master uses the newer TinyUSB NCM descriptor macro:

        TUD_CDC_NCM_DESCRIPTOR(..., mtu, interval, capabilities)

    The TinyUSB fork pinned by the ESP32-S3 dependency lockfile may still
    provide the older form:

        TUD_CDC_NCM_DESCRIPTOR(..., mtu)

    In that older macro the notification interval is already hard-coded to
    50 and the NCM capabilities byte is already hard-coded to 0.  Therefore
    removing the final ", 50, 0" from MicroPython's descriptor call preserves
    the same descriptor values.

    This patch is applied only when the installed managed TinyUSB component
    is positively detected as having the 9-argument macro.
    """

    import re

    tinyusb_header = (
        esp32_dir
        / "managed_components"
        / "espressif__tinyusb"
        / "src"
        / "device"
        / "usbd.h"
    )

    descriptor_source = (
        micropython_dir
        / "shared"
        / "tinyusb"
        / "mp_usbd_descriptor.c"
    )

    if not tinyusb_header.is_file():
        raise FileNotFoundError(
            "Could not locate ESP32 managed TinyUSB header: {}".format(
                tinyusb_header
            )
        )

    if not descriptor_source.is_file():
        raise FileNotFoundError(
            "Could not locate MicroPython USB descriptor source: {}".format(
                descriptor_source
            )
        )

    header_text = tinyusb_header.read_text(
        encoding="utf-8",
        errors="replace",
    )

    match = re.search(
        r"#define\s+TUD_CDC_NCM_DESCRIPTOR\s*\(([^)]*)\)",
        header_text,
    )

    if not match:
        raise RuntimeError(
            "Could not determine TUD_CDC_NCM_DESCRIPTOR signature from {}".format(
                tinyusb_header
            )
        )

    macro_args = [
        item.strip()
        for item in match.group(1).split(",")
        if item.strip()
    ]

    arg_count = len(macro_args)

    print()
    print(
        "TinyUSB TUD_CDC_NCM_DESCRIPTOR arguments:",
        arg_count,
    )

    if arg_count >= 11:
        print(
            "TinyUSB provides the newer NCM descriptor macro; "
            "no compatibility patch is required."
        )
        return

    if arg_count != 9:
        raise RuntimeError(
            "Unsupported TUD_CDC_NCM_DESCRIPTOR signature: "
            "{} arguments".format(
                arg_count
            )
        )

    source_text = descriptor_source.read_text(
        encoding="utf-8",
    )

    old_fragment = (
        "USBD_NCM_IN_OUT_MAX_SIZE, "
        "CFG_TUD_NET_MTU, 50, 0)"
    )

    new_fragment = (
        "USBD_NCM_IN_OUT_MAX_SIZE, "
        "CFG_TUD_NET_MTU)"
    )

    count = source_text.count(
        old_fragment
    )

    if count == 0:
        # If the source has already been patched, accept it.
        if new_fragment in source_text:
            print(
                "MicroPython NCM descriptor source is already "
                "compatible with the 9-argument TinyUSB macro."
            )
            return

        raise RuntimeError(
            "TinyUSB uses the 9-argument NCM descriptor macro, but the "
            "expected 11-argument MicroPython call was not found in {}".format(
                descriptor_source
            )
        )

    if count != 1:
        raise RuntimeError(
            "Expected exactly one MicroPython NCM descriptor call to patch; "
            "found {}".format(
                count
            )
        )

    descriptor_source.write_text(
        source_text.replace(
            old_fragment,
            new_fragment,
            1,
        ),
        encoding="utf-8",
    )

    print(
        "Applied ESP32 TinyUSB NCM descriptor compatibility patch:"
    )
    print(
        "  11-argument MicroPython call -> 9-argument TinyUSB call"
    )
    print(
        "  notification interval remains 50"
    )
    print(
        "  NCM capabilities remain 0"
    )



def patch_esp32_usbd_ncm_port_compat(micropython_dir):
    # Port MicroPython's generic USB-NCM implementation to ESP-IDF lwIP.
    source = micropython_dir / "extmod" / "network_usbd_ncm.c"

    if not source.is_file():
        raise FileNotFoundError(
            "Could not locate MicroPython USB-NCM source: {}".format(source)
        )

    data = source.read_text(encoding="utf-8")

    sentinel = "LILYGO_T_RELAY_S3_NCM ESP32 compatibility"
    if sentinel in data:
        print("ESP32 USB-NCM source compatibility patch already applied.")
        return

    include_old = '#include "lwip/dhcp.h"\n'
    include_new = '#include "lwip/dhcp.h"\n#include "lwip/tcpip.h"\n'

    if include_old not in data:
        include_lines = [
            line for line in data.splitlines()
            if line.lstrip().startswith("#include")
        ]
        raise RuntimeError(
            "Could not find lwIP include insertion point in {}. "
            "Observed includes: {}".format(
                source,
                " | ".join(include_lines[:40]),
            )
        )

    data = data.replace(include_old, include_new, 1)

    anchor = '#include "shared/netutils/dhcpserver.h"\n'

    compat = r"""
/*
 * LILYGO_T_RELAY_S3_NCM ESP32 compatibility
 *
 * MicroPython's generic USB-NCM implementation currently targets ports which
 * use MICROPY_PY_LWIP and the generic NIC registry/config helpers. ESP32 uses
 * ESP-IDF's lwIP integration instead.
 */
#if defined(ESP_PLATFORM)

#include "esp_mac.h"

#if !LWIP_TCPIP_CORE_LOCKING
#error "LILYGO_T_RELAY_S3_NCM requires CONFIG_LWIP_TCPIP_CORE_LOCKING=y"
#endif

#ifndef MICROPY_PY_LWIP_ENTER
#define MICROPY_PY_LWIP_ENTER LOCK_TCPIP_CORE();
#endif

#ifndef MICROPY_PY_LWIP_EXIT
#define MICROPY_PY_LWIP_EXIT UNLOCK_TCPIP_CORE();
#endif

#ifndef mod_network_register_nic
#define mod_network_register_nic(nic) ((void)(nic))
#endif

#ifndef tud_network_link_state
#define tud_network_link_state(rhport, is_up) do { (void)(rhport); (void)(is_up); } while (0)
#endif

static mp_obj_t esp32_ncm_ifconfig(struct netif *netif, size_t n_args, const mp_obj_t *args) {
    if (n_args == 0) {
        ip4_addr_t ip;
        ip4_addr_t netmask;
        ip4_addr_t gateway;
        ip_addr_t dns;

        MICROPY_PY_LWIP_ENTER
        ip4_addr_copy(ip, *netif_ip4_addr(netif));
        ip4_addr_copy(netmask, *netif_ip4_netmask(netif));
        ip4_addr_copy(gateway, *netif_ip4_gw(netif));
        ip_addr_copy(dns, *dns_getserver(0));
        MICROPY_PY_LWIP_EXIT

        mp_obj_t tuple[4] = {
            netutils_format_ipv4_addr((uint8_t *)&ip, NETUTILS_BIG),
            netutils_format_ipv4_addr((uint8_t *)&netmask, NETUTILS_BIG),
            netutils_format_ipv4_addr((uint8_t *)&gateway, NETUTILS_BIG),
            netutils_format_ipv4_addr((uint8_t *)&dns, NETUTILS_BIG),
        };

        return mp_obj_new_tuple(4, tuple);
    }

    if (!mp_obj_is_type(args[0], &mp_type_tuple) && !mp_obj_is_type(args[0], &mp_type_list)) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid arguments"));
    }

    mp_obj_t *items;
    mp_obj_get_array_fixed_n(args[0], 4, &items);

    ip4_addr_t ip;
    ip4_addr_t netmask;
    ip4_addr_t gateway;
    ip_addr_t dns;

    netutils_parse_ipv4_addr(items[0], (uint8_t *)&ip, NETUTILS_BIG);
    netutils_parse_ipv4_addr(items[1], (uint8_t *)&netmask, NETUTILS_BIG);
    netutils_parse_ipv4_addr(items[2], (uint8_t *)&gateway, NETUTILS_BIG);
    netutils_parse_ipv4_addr(items[3], (uint8_t *)&dns, NETUTILS_BIG);

    MICROPY_PY_LWIP_ENTER
    netif_set_addr(netif, &ip, &netmask, &gateway);
    dns_setserver(0, &dns);
    MICROPY_PY_LWIP_EXIT

    return mp_const_none;
}

static mp_obj_t esp32_ncm_ipconfig(struct netif *netif, size_t n_args, const mp_obj_t *args, mp_map_t *kwargs) {
    if (kwargs->used == 0) {
        if (n_args != 1) {
            mp_raise_TypeError(MP_ERROR_TEXT("must query one param"));
        }

        qstr key = mp_obj_str_get_qstr(args[0]);

        if (key == MP_QSTR_addr4) {
            ip4_addr_t ip;
            ip4_addr_t netmask;

            MICROPY_PY_LWIP_ENTER
            ip4_addr_copy(ip, *netif_ip4_addr(netif));
            ip4_addr_copy(netmask, *netif_ip4_netmask(netif));
            MICROPY_PY_LWIP_EXIT

            mp_obj_t tuple[2] = {
                netutils_format_ipv4_addr((uint8_t *)&ip, NETUTILS_BIG),
                netutils_format_ipv4_addr((uint8_t *)&netmask, NETUTILS_BIG),
            };
            return mp_obj_new_tuple(2, tuple);
        }

        if (key == MP_QSTR_gw4) {
            ip4_addr_t gateway;

            MICROPY_PY_LWIP_ENTER
            ip4_addr_copy(gateway, *netif_ip4_gw(netif));
            MICROPY_PY_LWIP_EXIT

            return netutils_format_ipv4_addr((uint8_t *)&gateway, NETUTILS_BIG);
        }

        if (key == MP_QSTR_dns) {
            ip_addr_t dns;

            MICROPY_PY_LWIP_ENTER
            ip_addr_copy(dns, *dns_getserver(0));
            MICROPY_PY_LWIP_EXIT

            char address[IPADDR_STRLEN_MAX];
            ipaddr_ntoa_r(&dns, address, sizeof(address));
            return mp_obj_new_str_from_cstr(address);
        }

        mp_raise_ValueError(MP_ERROR_TEXT("unexpected key"));
    }

    if (n_args != 0) {
        mp_raise_TypeError(MP_ERROR_TEXT("can't specify pos and kw args"));
    }

    mp_raise_ValueError(MP_ERROR_TEXT("setting ipconfig is not supported on ESP32 USB NCM"));
}

#define mod_network_nic_ifconfig esp32_ncm_ifconfig
#define mod_network_nic_ipconfig esp32_ncm_ipconfig

#endif /* ESP_PLATFORM */
"""

    if anchor not in data:
        include_lines = [
            line for line in data.splitlines()
            if line.lstrip().startswith("#include")
        ]
        raise RuntimeError(
            "Could not find USB-NCM compatibility insertion point in {}. "
            "Observed includes: {}".format(
                source,
                " | ".join(include_lines[:40]),
            )
        )

    data = data.replace(anchor, anchor + compat, 1)

    old_input = """        netif_init_cb,
        ethernet_input
        );"""

    new_input = """        netif_init_cb,
        tcpip_input
        );"""

    if old_input not in data:
        raise RuntimeError(
            "Could not find USB-NCM netif input callback in {}".format(source)
        )

    data = data.replace(old_input, new_input, 1)

    old_mac = "    mp_hal_get_mac(MP_HAL_MAC_ETH0, tud_network_mac_address);"
    new_mac = """    if (esp_read_mac(tud_network_mac_address, ESP_MAC_ETH) != ESP_OK) {
        mp_raise_OSError(MP_EIO);
    }"""

    if old_mac not in data:
        raise RuntimeError(
            "Could not find generic USB-NCM MAC address call in {}".format(source)
        )

    data = data.replace(old_mac, new_mac, 1)

    # The driver-facing RX callback now feeds tcpip_input(), which is the
    # thread-safe lwIP ingress API for NO_SYS=0 ports. Do not hold the TCP/IP
    # core lock while calling it. Patch structurally by function name instead
    # of matching the entire upstream function body verbatim.

    def strip_lwip_lock_lines_from_function(source_text, signature):
        function_start = source_text.find(signature)

        if function_start < 0:
            raise RuntimeError(
                "Could not find function {} in {}".format(
                    signature,
                    source,
                )
            )

        brace_start = source_text.find("{", function_start)

        if brace_start < 0:
            raise RuntimeError(
                "Could not find opening brace for {}".format(signature)
            )

        depth = 0
        function_end = None

        for index in range(brace_start, len(source_text)):
            char = source_text[index]

            if char == "{":
                depth += 1

            elif char == "}":
                depth -= 1

                if depth == 0:
                    function_end = index + 1
                    break

        if function_end is None:
            raise RuntimeError(
                "Could not find closing brace for {}".format(signature)
            )

        function_text = source_text[function_start:function_end]

        original = function_text

        filtered_lines = []

        for line in function_text.splitlines(True):
            stripped = line.strip()

            if stripped in (
                "MICROPY_PY_LWIP_ENTER",
                "MICROPY_PY_LWIP_EXIT",
            ):
                continue

            filtered_lines.append(line)

        function_text = "".join(filtered_lines)

        if function_text == original:
            print(
                "No nested lwIP lock lines found in {}; "
                "nothing to remove.".format(signature)
            )
        else:
            print(
                "Removed nested lwIP core locking from {}".format(
                    signature
                )
            )

        return (
            source_text[:function_start]
            + function_text
            + source_text[function_end:]
        )

    data = strip_lwip_lock_lines_from_function(
        data,
        "bool tud_network_recv_cb(",
    )

    data = strip_lwip_lock_lines_from_function(
        data,
        "uint16_t tud_network_xmit_cb(",
    )

    source.write_text(data, encoding="utf-8")

    print()
    print("Applied ESP32 USB-NCM network compatibility patch:")
    print("  ESP-IDF lwIP core locking")
    print("  ESP-IDF Ethernet MAC via esp_read_mac(..., ESP_MAC_ETH)")
    print("  ESP32-local ifconfig/ipconfig query helpers")
    print("  generic NIC registration disabled")
    print("  RX routed through tcpip_input() without nested core locking")
    print("  TinyUSB TX callback avoids recursive lwIP core locking")
    print("  legacy TinyUSB link-state compatibility")


def patch_dhcpserver_for_esp32_ncm(micropython_dir):
    """Compile MicroPython's shared DHCP server for the ESP32 USB-NCM build.

    shared/netutils/dhcpserver.c normally compiles its implementation only when
    MICROPY_PY_LWIP is enabled.  The ESP32 port uses ESP-IDF's lwIP integration
    and does not enable MICROPY_PY_LWIP, but network.USBD_NCM still uses this
    shared DHCP server when MICROPY_PY_NETWORK_USBD_NCM_DHCP_SERVER is enabled.

    For this custom build, extend the existing guard rather than enabling
    MICROPY_PY_LWIP globally.
    """

    source = (
        micropython_dir
        / "shared"
        / "netutils"
        / "dhcpserver.c"
    )

    if not source.is_file():
        raise FileNotFoundError(
            "Could not locate MicroPython DHCP server source: {}".format(
                source
            )
        )

    data = source.read_text(
        encoding="utf-8"
    )

    old_guard = "#if MICROPY_PY_LWIP"
    new_guard = (
        "#if MICROPY_PY_LWIP || "
        "MICROPY_PY_NETWORK_USBD_NCM_DHCP_SERVER"
    )

    if new_guard in data:
        print(
            "ESP32 USB-NCM DHCP server compatibility patch "
            "already applied."
        )
        return

    count = data.count(old_guard)

    if count != 1:
        raise RuntimeError(
            "Expected exactly one MICROPY_PY_LWIP guard in {}; "
            "found {}".format(
                source,
                count,
            )
        )

    source.write_text(
        data.replace(
            old_guard,
            new_guard,
            1,
        ),
        encoding="utf-8",
    )

    print(
        "Applied ESP32 USB-NCM DHCP server compatibility patch:"
    )
    print(
        "  shared/netutils/dhcpserver.c now builds when"
    )
    print(
        "  MICROPY_PY_NETWORK_USBD_NCM_DHCP_SERVER is enabled"
    )
    print(
        "  MICROPY_PY_LWIP remains disabled globally on ESP32"
    )



def patch_esp32_ncm_tx_readiness(micropython_dir):
    """Use tud_mounted() instead of tud_ready() for ESP32 NCM TX."""

    source = micropython_dir / "extmod" / "network_usbd_ncm.c"

    if not source.is_file():
        raise FileNotFoundError(
            "Could not locate MicroPython USB-NCM source: {}".format(source)
        )

    data = source.read_text(encoding="utf-8")

    old = "if (!tud_ready() || !tud_network_can_xmit(p->tot_len)) {"
    new = "if (!tud_mounted() || !tud_network_can_xmit(p->tot_len)) {"

    if new in data:
        print("ESP32 NCM TX readiness patch already applied (tud_mounted).")
        return

    if old not in data:
        raise RuntimeError(
            "Could not find NCM TX readiness condition in {}".format(source)
        )

    source.write_text(data.replace(old, new, 1), encoding="utf-8")

    print("Applied ESP32 USB-NCM TX readiness compatibility patch:")
    print("  linkoutput_fn now uses tud_mounted() instead of tud_ready()")
    print("  prevents initial ARP/DHCP replies being dropped after enumeration")



def install_esp32_native_ncm_backend(custom_dir, micropython_dir):
    """Replace the generic USB-NCM source with the ESP32 esp_netif backend."""

    source = (
        custom_dir
        / "boards"
        / "LILYGO_T_RELAY_S3_NCM"
        / "network_usbd_ncm_esp32.c"
    )

    destination = (
        micropython_dir
        / "extmod"
        / "network_usbd_ncm.c"
    )

    if not source.is_file():
        raise FileNotFoundError(
            "Missing ESP32 native NCM backend: {}".format(source)
        )

    if not destination.is_file():
        raise FileNotFoundError(
            "Missing upstream MicroPython NCM source target: {}".format(
                destination
            )
        )

    shutil.copy2(source, destination)

    print()
    print("Installed ESP32-native USB-NCM backend:")
    print("  TinyUSB NCM framing/descriptors")
    print("  ESP-IDF esp_netif Ethernet stack")
    print("  ESP-IDF DHCP server")
    print("  USB device address: 192.168.7.1/24")
    print("  no USB default gateway")


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
            / "micropython-lilygo-t-relay-s3-ncm-build"
        )
    )

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("========================================")
    print(" MicroPython LILYGO_T_RELAY_S3_NCM Build")
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

    # Current MicroPython master uses the newer 11-argument TinyUSB NCM
    # descriptor macro, while the ESP32 managed TinyUSB fork can still expose
    # the older 9-argument form.  Detect and adapt only when required.
    patch_tinyusb_ncm_descriptor_compat(
        micropython_dir,
        esp32_dir,
    )

    # Replace the generic lwIP USB-NCM implementation with the ESP32-native
    # esp_netif backend. Descriptor compatibility is handled separately above.
    install_esp32_native_ncm_backend(
        custom_dir,
        micropython_dir,
    )

    print("Building ESP32-native USB-NCM + Octal-PSRAM MicroPython...")

    # GitHub Actions logs should include the complete compiler/link command on
    # failure.  Local builds remain quieter unless CI is set.
    make_command = "make {}".format(board_args)
    if os.environ.get("CI"):
        # MicroPython's ESP32 Makefile checks BUILD_VERBOSE=1 and then passes
        # --verbose through to idf.py.  V=1 only affects Make's own command
        # echoing and does not enable idf.py/Ninja verbose output.
        make_command += " BUILD_VERBOSE=1"

    try:
        idf_shell(
            idf_dir,
            esp32_dir,
            make_command,
        )
    except subprocess.CalledProcessError:
        print_idf_failure_logs(
            esp32_dir,
            config["board"],
            config["variant"],
        )
        raise

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
