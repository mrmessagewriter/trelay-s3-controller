#!/usr/bin/env python3
"""Build MicroPython master for the LILYGO T-Relay ESP32-S3 with USB CDC-NCM.

This builder deliberately keeps MicroPython's upstream extmod/network_usbd_ncm.c
implementation.  It applies only the ESP32 port glue currently needed because
the ESP32 port uses ESP-IDF's threaded lwIP integration instead of the generic
MICROPY_PY_LWIP integration used by the upstream NCM source.

It also backports the TinyUSB NCM link-state API only when the TinyUSB component
pinned by MicroPython master does not yet expose that API.  This is important:
the link-state function is never stubbed out or converted to a no-op.

Windows:
    python firmware\\tools\\build_micropython_ncm.py --bootstrap

Linux / WSL:
    python3 firmware/tools/build_micropython_ncm.py --bootstrap

Subsequent builds can omit --bootstrap.  Add --clean for a full ESP32 rebuild.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Clone/update dependencies and install the ESP-IDF toolchain.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Run a full clean before building.",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help=(
            "Build workspace. Defaults to "
            "~/.cache/micropython-lilygo-t-relay-s3-ncm-build."
        ),
    )
    parser.add_argument("--inside-wsl", action="store_true", help=argparse.SUPPRESS)
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
    return run(command, cwd=cwd, capture=True).stdout.strip()


def get_repo_paths():
    tools_dir = Path(__file__).resolve().parent
    firmware_dir = tools_dir.parent
    repo_root = firmware_dir.parent
    return repo_root, firmware_dir, firmware_dir / "micropython"


def relaunch_under_wsl(args):
    if shutil.which("wsl.exe") is None:
        raise RuntimeError(
            "WSL is required for the ESP32 MicroPython build on Windows.\n"
            "Install it with: wsl --install -d Ubuntu"
        )

    script_wsl = capture(
        ["wsl.exe", "wslpath", "-a", str(Path(__file__).resolve())]
    )
    command = ["wsl.exe", "python3", script_wsl, "--inside-wsl"]
    if args.bootstrap:
        command.append("--bootstrap")
    if args.clean:
        command.append("--clean")
    if args.work_dir:
        command.extend(["--work-dir", args.work_dir])

    print("\nRe-launching MicroPython build inside WSL...")
    return subprocess.call(command)


def require_command(name, hint):
    if shutil.which(name) is None:
        raise RuntimeError("Required command {!r} was not found.\n{}".format(name, hint))


def load_build_config(custom_dir):
    path = custom_dir / "micropython_build.json"
    if not path.is_file():
        raise FileNotFoundError("Missing MicroPython build config: {}".format(path))
    return json.loads(path.read_text(encoding="utf-8"))


def clone_or_update(url, ref, destination, recursive=False):
    if not destination.exists():
        command = ["git", "clone", "--depth", "1", "--branch", ref]
        if recursive:
            command.append("--recursive")
        command.extend([url, str(destination)])
        run(command)
    else:
        run(["git", "fetch", "--depth", "1", "origin", ref], cwd=destination)
        run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=destination)
        run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=destination)
        run(["git", "clean", "-ffd"], cwd=destination)

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
    if not idf_dir.exists() and not bootstrap:
        raise RuntimeError("ESP-IDF is missing. Re-run once with --bootstrap.")

    if bootstrap or not idf_dir.exists():
        clone_or_update(
            config["esp_idf_repository"],
            config["esp_idf_ref"],
            idf_dir,
            recursive=True,
        )
        print("\nInstalling ESP-IDF toolchain for ESP32-S3...")
        run(["bash", "./install.sh", "esp32s3"], cwd=idf_dir)

    if not (idf_dir / "export.sh").is_file():
        raise RuntimeError("ESP-IDF checkout is incomplete. Re-run with --bootstrap.")
    return idf_dir


def ensure_micropython(config, work_dir):
    micropython_dir = work_dir / "micropython"
    clone_or_update(
        config["micropython_repository"],
        config["micropython_ref"],
        micropython_dir,
        recursive=True,
    )
    ncm = micropython_dir / "extmod" / "network_usbd_ncm.c"
    if not ncm.is_file():
        raise RuntimeError(
            "Selected MicroPython revision has no extmod/network_usbd_ncm.c"
        )
    return micropython_dir


def install_custom_board(custom_dir, micropython_dir, board_name):
    source = custom_dir / "boards" / board_name
    destination = micropython_dir / "ports" / "esp32" / "boards" / board_name
    if not source.is_dir():
        raise FileNotFoundError("Missing custom board definition: {}".format(source))
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    # mpconfigboard.cmake is evaluated before esp32_common.cmake initializes
    # MICROPY_DIR.  The board therefore resolves its extra shared DHCP source
    # relative to its own installed directory.  Verify that path now so a bad
    # board-source path fails here instead of later as an opaque CMake error.
    dhcp_source = (
        destination / "../../../.." / "shared" / "netutils" / "dhcpserver.c"
    ).resolve()
    if not dhcp_source.is_file():
        raise RuntimeError(
            "Custom board DHCP source path does not resolve: {}".format(
                dhcp_source
            )
        )

    print("Installed custom MicroPython board:", destination)
    print("Verified upstream DHCP source:", dhcp_source)


def idf_shell(idf_dir, cwd, command):
    shell_command = (
        "set -e; "
        'source "{}" >/dev/null; '
        "export IDF_COMPONENT_MANAGER=1; "
        "{}".format(idf_dir / "export.sh", command)
    )
    run(["bash", "-lc", shell_command], cwd=cwd)


def patch_tinyusb_descriptor_compat(micropython_dir, esp32_dir):
    """Adapt only the descriptor macro call if ESP32's TinyUSB is older."""
    header = (
        esp32_dir
        / "managed_components"
        / "espressif__tinyusb"
        / "src"
        / "device"
        / "usbd.h"
    )
    source = micropython_dir / "shared" / "tinyusb" / "mp_usbd_descriptor.c"
    if not header.is_file() or not source.is_file():
        raise FileNotFoundError("Unable to locate TinyUSB descriptor sources")

    match = re.search(
        r"#define\s+TUD_CDC_NCM_DESCRIPTOR\s*\(([^)]*)\)",
        header.read_text(encoding="utf-8", errors="replace"),
    )
    if not match:
        raise RuntimeError("Could not determine TUD_CDC_NCM_DESCRIPTOR signature")

    arg_count = len([x for x in match.group(1).split(",") if x.strip()])
    print("TinyUSB TUD_CDC_NCM_DESCRIPTOR arguments:", arg_count)
    if arg_count >= 11:
        return
    if arg_count != 9:
        raise RuntimeError("Unsupported NCM descriptor macro: {} args".format(arg_count))

    data = source.read_text(encoding="utf-8")
    old = "USBD_NCM_IN_OUT_MAX_SIZE, CFG_TUD_NET_MTU, 50, 0)"
    new = "USBD_NCM_IN_OUT_MAX_SIZE, CFG_TUD_NET_MTU)"
    if old in data:
        source.write_text(data.replace(old, new, 1), encoding="utf-8")
        print("Applied 11-argument -> 9-argument TinyUSB NCM descriptor shim.")
    elif new not in data:
        raise RuntimeError("Expected NCM descriptor call was not found")


def patch_tinyusb_link_state_compat(esp32_dir):
    """Backport the NCM link-state API only if the pinned ESP32 TinyUSB lacks it.

    MicroPython master calls tud_network_link_state() and provides
    tud_network_default_link_state_cb(). Some ESP32 managed-component revisions
    predate those APIs. This compatibility layer keeps real carrier signaling;
    it never replaces tud_network_link_state() with a no-op.
    """
    tinyusb = esp32_dir / "managed_components" / "espressif__tinyusb"
    source = tinyusb / "src" / "class" / "net" / "ncm_device.c"
    header = tinyusb / "src" / "class" / "net" / "net_device.h"
    if not source.is_file() or not header.is_file():
        raise FileNotFoundError("Could not locate ESP32 TinyUSB NCM sources")

    hdata = header.read_text(encoding="utf-8")
    sdata = source.read_text(encoding="utf-8")

    has_link_api = (
        "tud_network_link_state" in hdata
        and "tud_network_link_state" in sdata
    )
    has_2026_carrier_fix = (
        "ncm_link_state_task" in sdata
        and "usbd_defer_func(ncm_link_state_task" in sdata
        and "link state notification deferred (interface not active)" in sdata
        and "Reset notification state to send link state update when interface is re-activated" in sdata
    )

    if has_link_api and has_2026_carrier_fix:
        print("TinyUSB already provides the 2026 NCM carrier/re-enumeration fix.")
        return

    if has_link_api:
        print("TinyUSB has the NCM link API but lacks the 2026 carrier fix; patching it...")

        # TinyUSB 0.19.0 introduced tud_network_link_state(), but its initial
        # implementation can lose NETWORK_CONNECTION notifications and does
        # not re-arm the notification sequence when the host switches the NCM
        # data interface to alt=0 and back to alt=1. Windows uses that sequence
        # when a network adapter is disabled/enabled, leaving the adapter stuck
        # at NO-CARRIER. Backport the current TinyUSB behavior while retaining
        # the rest of the pinned component.

        if "tud_network_default_link_state_cb" not in hdata:
            decl = "void tud_network_link_state(uint8_t rhport, bool is_up);"
            if decl not in hdata:
                raise RuntimeError("TinyUSB existing link-state declaration not found")
            hdata = hdata.replace(
                decl,
                decl + "\n// Initial carrier state used after USB reset/re-enumeration."
                + "\nbool tud_network_default_link_state_cb(void);",
                1,
            )

        if "TU_ATTR_WEAK bool tud_network_default_link_state_cb(void)" not in sdata:
            anchor_cb = "TU_ATTR_ALIGNED(4) static const ntb_parameters_t ntb_parameters = {"
            if anchor_cb not in sdata:
                raise RuntimeError("TinyUSB existing NCM NTB anchor not found")
            weak_cb = (
                "TU_ATTR_WEAK bool tud_network_default_link_state_cb(void) {\n"
                "  return true;\n"
                "}\n\n"
            )
            sdata = sdata.replace(anchor_cb, weak_cb + anchor_cb, 1)

        old_link_fn = r'''/**
 * Set the link state and send notification to host
 */
void tud_network_link_state(uint8_t rhport, bool is_up) {
  TU_LOG_DRV("tud_network_link_state(%d, %d)\n", rhport, is_up);
  if (ncm_interface.link_is_up == is_up) {
    // No change in link state
    return;
  }

  ncm_interface.link_is_up = is_up;

  // Only send notification if we have an active data interface
  if (ncm_interface.itf_data_alt != 1) {
    TU_LOG_DRV("  link state notification skipped (interface not active)\n");
    return;
  }

  // Reset notification state to send link state update
  ncm_interface.notification_xmit_state = NOTIFICATION_CONNECTED;
  // Trigger notification transmission
  notification_xmit(rhport, false);
}
'''
        new_link_fn = r'''/**
 * usbd-task trampoline for tud_network_link_state().
 *
 * Keep all notification-state mutations on the TinyUSB task. If a carrier
 * transition collides with an in-flight notification, resetting the state
 * machine means the endpoint-completion callback will deliver the new state.
 */
static void ncm_link_state_task(void *param) {
  uintptr_t const arg = (uintptr_t) param;
  uint8_t const rhport = (uint8_t) (arg >> 1);
  bool const is_up = (arg & 1u) != 0;

  if (ncm_interface.link_is_up == is_up) {
    return;
  }

  ncm_interface.link_is_up = is_up;

  if (ncm_interface.itf_data_alt != 1) {
    TU_LOG_DRV("  link state notification deferred (interface not active)\n");
    return;
  }

  ncm_interface.notification_xmit_state = NOTIFICATION_SPEED;
  notification_xmit(rhport, false);
}

/** Set the link state and notify the host. */
void tud_network_link_state(uint8_t rhport, bool is_up) {
  TU_LOG_DRV("tud_network_link_state(%d, %d)\n", rhport, is_up);
  uintptr_t const arg = ((uintptr_t) rhport << 1) | (is_up ? 1u : 0u);
  usbd_defer_func(ncm_link_state_task, (void *) arg, false);
}
'''
        if old_link_fn in sdata:
            sdata = sdata.replace(old_link_fn, new_link_fn, 1)
        elif "usbd_defer_func(ncm_link_state_task" not in sdata:
            raise RuntimeError("TinyUSB 0.19 link-state function anchor not found")

        old_init = '''  // Default link state - can be configured via CFG_TUD_NCM_DEFAULT_LINK_UP
  #ifdef CFG_TUD_NCM_DEFAULT_LINK_UP
  ncm_interface.link_is_up = CFG_TUD_NCM_DEFAULT_LINK_UP;
  #else
  ncm_interface.link_is_up = true; // Default to link up if not set.
  #endif
'''
        new_init = '''  // Query the application for the desired carrier state on every USB reset.
  ncm_interface.link_is_up = tud_network_default_link_state_cb();
'''
        if old_init in sdata:
            sdata = sdata.replace(old_init, new_init, 1)
        elif "ncm_interface.link_is_up = tud_network_default_link_state_cb();" not in sdata:
            raise RuntimeError("TinyUSB 0.19 netd_init carrier-state anchor not found")

        old_set_itf = '''          if (ncm_interface.itf_data_alt == 1) {
            tud_network_recv_renew_r(rhport);
            notification_xmit(rhport, false);
          }
          tud_control_status(rhport, request);'''
        new_set_itf = '''          if (ncm_interface.itf_data_alt == 1) {
            tud_network_recv_renew_r(rhport);
            notification_xmit(rhport, false);
          } else {
            // Re-arm speed + NETWORK_CONNECTION for the next alt=1.
            // Windows Disable/Enable commonly performs alt=0 -> alt=1 without
            // a full USB bus reset. Without this, the state remains DONE and
            // the host never receives carrier-up again.
            ncm_interface.notification_xmit_state = NOTIFICATION_SPEED;
          }
          tud_control_status(rhport, request);'''
        if old_set_itf in sdata:
            sdata = sdata.replace(old_set_itf, new_set_itf, 1)
        elif (
            "Re-arm speed + NETWORK_CONNECTION for the next alt=1" not in sdata
            and "Reset notification state to send link state update when interface is re-activated" not in sdata
        ):
            raise RuntimeError("TinyUSB 0.19 SET_INTERFACE re-arm anchor not found")

        header.write_text(hdata, encoding="utf-8")
        source.write_text(sdata, encoding="utf-8")
        print("TinyUSB 0.19 NCM carrier/re-enumeration fix applied.")
        return

    print("Backporting TinyUSB NCM link-state signaling API...")

    # Public API declarations.
    anchor_h = "extern uint8_t tud_network_mac_address[6];"
    if anchor_h not in hdata:
        raise RuntimeError("TinyUSB NCM header anchor not found")
    hdata = hdata.replace(
        anchor_h,
        anchor_h
        + "\n\n// NCM link/carrier state support used by MicroPython USBD_NCM."
        + "\nbool tud_network_default_link_state_cb(void);"
        + "\nvoid tud_network_link_state(uint8_t rhport, bool is_up);",
        1,
    )

    # Driver state.
    anchor_state = (
        "bool notification_xmit_is_running;                    "
        "// notification is currently transmitted"
    )
    if anchor_state not in sdata:
        raise RuntimeError("TinyUSB NCM notification state anchor not found")
    sdata = sdata.replace(
        anchor_state,
        anchor_state
        + "\n  bool link_is_up;                                      "
        "// current network carrier state"
        + "\n  bool link_notify_pending;                             "
        "// carrier notification must be retried",
        1,
    )

    # Default-state callback. MicroPython supplies a strong implementation.
    anchor_cb = "TU_ATTR_ALIGNED(4) static const ntb_parameters_t ntb_parameters = {"
    if anchor_cb not in sdata:
        raise RuntimeError("TinyUSB NCM NTB anchor not found")
    weak_cb = (
        "TU_ATTR_WEAK bool tud_network_default_link_state_cb(void) {\n"
        "  return true;\n"
        "}\n\n"
    )
    sdata = sdata.replace(anchor_cb, weak_cb + anchor_cb, 1)

    # The NETWORK_CONNECTION notification must report the actual carrier state.
    old_connected = ".wValue = 1 /* Connected */,"
    if old_connected not in sdata:
        raise RuntimeError("TinyUSB fixed NETWORK_CONNECTION state was not found")
    sdata = sdata.replace(
        old_connected,
        ".wValue = ncm_interface.link_is_up ? 1 : 0, /* Dynamic link state */",
        1,
    )

    # Mark a successfully submitted NETWORK_CONNECTION as satisfying any
    # pending carrier update, and mark the notification endpoint idle after
    # the speed/connection sequence completes.
    connected_done = """    ncm_interface.notification_xmit_state = NOTIFICATION_DONE;
    ncm_interface.notification_xmit_is_running = true;"""
    if connected_done not in sdata:
        raise RuntimeError("TinyUSB connected-notification completion anchor not found")
    sdata = sdata.replace(
        connected_done,
        """    ncm_interface.notification_xmit_state = NOTIFICATION_DONE;
    ncm_interface.notification_xmit_is_running = true;
    ncm_interface.link_notify_pending = false;""",
        1,
    )

    finished = '  } else {\n    TU_LOG_DRV("  NOTIFICATION_FINISHED\\n");\n  }'
    if finished not in sdata:
        raise RuntimeError("TinyUSB notification-finished anchor not found")
    sdata = sdata.replace(
        finished,
        '  } else {\n    TU_LOG_DRV("  NOTIFICATION_FINISHED\\n");\n    ncm_interface.notification_xmit_is_running = false;\n  }',
        1,
    )

    # Initialize carrier state on every USB bus reset/re-enumeration.
    init_anchor = "  for (int i = 0; i < RECV_NTB_N; ++i) {\n    ncm_interface.recv_free_ntb[i] = &ncm_epbuf.recv[i].ntb;\n  }\n} // netd_init"
    if init_anchor not in sdata:
        raise RuntimeError("TinyUSB netd_init anchor not found")
    sdata = sdata.replace(
        init_anchor,
        init_anchor.replace(
            "\n} // netd_init",
            "\n  ncm_interface.link_is_up = tud_network_default_link_state_cb();\n} // netd_init",
        ),
        1,
    )

    # Serialize the state transition onto TinyUSB's device task.  Initial calls
    # before SET_INTERFACE only update desired state; SET_INTERFACE later emits
    # the notification using that state.
    api_anchor = "//-----------------------------------------------------------------------------\n//\n// all the netd_*() stuff (interface TinyUSB -> driver)"
    if api_anchor not in sdata:
        raise RuntimeError("TinyUSB netd section anchor not found")
    api_impl = r'''static void ncm_link_state_task(void *ctx) {
  uintptr_t const packed = (uintptr_t) ctx;
  uint8_t const rhport = (uint8_t) (packed >> 1);
  bool const is_up = (packed & 1u) != 0;

  if (ncm_interface.link_is_up == is_up) {
    return;
  }

  ncm_interface.link_is_up = is_up;
  ncm_interface.link_notify_pending = true;

  if (ncm_interface.itf_data_alt == 1 && !ncm_interface.notification_xmit_is_running) {
    // Link toggles do not change speed, so only NETWORK_CONNECTION is needed.
    ncm_interface.notification_xmit_state = NOTIFICATION_CONNECTED;
    notification_xmit(rhport, false);
  }
}

void tud_network_link_state(uint8_t rhport, bool is_up) {
  uintptr_t const packed = ((uintptr_t) rhport << 1) | (is_up ? 1u : 0u);
  usbd_defer_func(ncm_link_state_task, (void *) packed, false);
}

'''
    sdata = sdata.replace(api_anchor, api_impl + api_anchor, 1)

    # If a carrier change collided with an in-flight notification, retry it
    # after the notification endpoint becomes idle. This is the essential
    # behavior from TinyUSB's 2026 NCM carrier-loss fix.
    xfer_anchor = """  } else if (ep_addr == ncm_interface.ep_notif) {
    // next transfer on notification channel
    notification_xmit(rhport, true);
  }"""
    if xfer_anchor not in sdata:
        raise RuntimeError("TinyUSB notification xfer callback anchor not found")
    sdata = sdata.replace(
        xfer_anchor,
        """  } else if (ep_addr == ncm_interface.ep_notif) {
    // next transfer on notification channel
    notification_xmit(rhport, true);
    if (!ncm_interface.notification_xmit_is_running && ncm_interface.link_notify_pending) {
      ncm_interface.notification_xmit_state = NOTIFICATION_CONNECTED;
      notification_xmit(rhport, false);
    }
  }""",
        1,
    )

    header.write_text(hdata, encoding="utf-8")
    source.write_text(sdata, encoding="utf-8")
    print("TinyUSB NCM carrier signaling backport applied.")


def _function_without_lock_lines(data, signature):
    start = data.find(signature)
    if start < 0:
        raise RuntimeError("Could not find function {}".format(signature))
    brace = data.find("{", start)
    depth = 0
    end = None
    for i in range(brace, len(data)):
        if data[i] == "{":
            depth += 1
        elif data[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise RuntimeError("Could not find end of {}".format(signature))
    body = data[start:end]
    body = "".join(
        line
        for line in body.splitlines(True)
        if line.strip() not in ("MICROPY_PY_LWIP_ENTER", "MICROPY_PY_LWIP_EXIT")
    )
    return data[:start] + body + data[end:]


def _replace_required(data, old, new, label):
    count = data.count(old)
    if count != 1:
        raise RuntimeError(
            "Expected exactly one {} anchor; found {}".format(label, count)
        )
    return data.replace(old, new, 1)


def patch_esp32_upstream_ncm_port_glue(micropython_dir):
    """Make upstream network_usbd_ncm.c use ESP32's threaded ESP-IDF lwIP.

    This intentionally preserves upstream ncm_auto_init(), ncm_set_link(),
    active(), isconnected(), DHCP behavior, link-local address generation, and
    TinyUSB carrier notification calls.
    """
    source = micropython_dir / "extmod" / "network_usbd_ncm.c"
    data = source.read_text(encoding="utf-8")
    sentinel = "SPRINKLERS1 ESP32 upstream-NCM glue"
    if sentinel in data:
        return

    include = '#include "lwip/dhcp.h"\n'
    if include not in data:
        raise RuntimeError("Upstream NCM lwIP include anchor not found")
    data = data.replace(include, include + '#include "lwip/tcpip.h"\n', 1)

    anchor = '#include "shared/netutils/dhcpserver.h"\n'
    if anchor not in data:
        raise RuntimeError("Upstream NCM compatibility insertion anchor not found")

    compat = r'''
/* SPRINKLERS1 ESP32 upstream-NCM glue
 *
 * Keep MicroPython's upstream NCM implementation and adapt only its generic
 * lwIP helpers to ESP-IDF's threaded lwIP port.
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

// ESP32 sockets use ESP-IDF's global lwIP stack rather than MicroPython's
// generic NIC registry.
#ifndef mod_network_register_nic
#define mod_network_register_nic(nic) ((void)(nic))
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
    mp_raise_ValueError(MP_ERROR_TEXT("setting ifconfig is not supported on ESP32 USB NCM"));
}

static mp_obj_t esp32_ncm_ipconfig(struct netif *netif, size_t n_args, const mp_obj_t *args, mp_map_t *kwargs) {
    if (kwargs->used != 0 || n_args != 1) {
        mp_raise_ValueError(MP_ERROR_TEXT("setting ipconfig is not supported on ESP32 USB NCM"));
    }
    qstr key = mp_obj_str_get_qstr(args[0]);
    if (key == MP_QSTR_addr4) {
        ip4_addr_t ip;
        ip4_addr_t mask;
        MICROPY_PY_LWIP_ENTER
        ip4_addr_copy(ip, *netif_ip4_addr(netif));
        ip4_addr_copy(mask, *netif_ip4_netmask(netif));
        MICROPY_PY_LWIP_EXIT
        mp_obj_t tuple[2] = {
            netutils_format_ipv4_addr((uint8_t *)&ip, NETUTILS_BIG),
            netutils_format_ipv4_addr((uint8_t *)&mask, NETUTILS_BIG),
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

#define mod_network_nic_ifconfig esp32_ncm_ifconfig
#define mod_network_nic_ipconfig esp32_ncm_ipconfig
#endif
'''
    data = data.replace(anchor, anchor + compat, 1)

    # ESP32 does not provide the generic mp_hal_get_mac Ethernet helper.
    old_mac = "    mp_hal_get_mac(MP_HAL_MAC_ETH0, tud_network_mac_address);"
    new_mac = (
        "    if (esp_read_mac(tud_network_mac_address, ESP_MAC_ETH) != ESP_OK) {\n"
        "        mp_raise_OSError(MP_EIO);\n"
        "    }"
    )
    if old_mac not in data:
        raise RuntimeError("Upstream NCM MAC helper anchor not found")
    data = data.replace(old_mac, new_mac, 1)

    # ESP32 uses NO_SYS=0. tcpip_input is the thread-safe ingress function.
    old_input = "        netif_init_cb,\n        ethernet_input\n        );"
    new_input = "        netif_init_cb,\n        tcpip_input\n        );"
    if old_input not in data:
        raise RuntimeError("Upstream NCM netif input anchor not found")
    data = data.replace(old_input, new_input, 1)

    # Don't hold the TCP/IP core lock while posting a pbuf back to tcpip_input,
    # and don't recursively lock when TinyUSB copies a frame for TX.
    data = _function_without_lock_lines(data, "bool tud_network_recv_cb(")
    data = _function_without_lock_lines(data, "uint16_t tud_network_xmit_cb(")

    # Serialize link flag changes with the ESP-IDF lwIP core. Keep the TinyUSB
    # carrier notification itself outside the lwIP lock.
    old_link = """static void ncm_set_link(bool up) {
    if (up) {
        netif_set_link_up(&ncm_obj.netif);
    } else {
        netif_set_link_down(&ncm_obj.netif);
    }
    tud_network_link_state(TUD_OPT_RHPORT, up);
}"""
    new_link = """static void ncm_set_link(bool up) {
    MICROPY_PY_LWIP_ENTER
    if (up) {
        netif_set_link_up(&ncm_obj.netif);
    } else {
        netif_set_link_down(&ncm_obj.netif);
    }
    MICROPY_PY_LWIP_EXIT
    tud_network_link_state(TUD_OPT_RHPORT, up);
}"""
    if old_link not in data:
        raise RuntimeError("Upstream NCM ncm_set_link anchor not found")
    data = data.replace(old_link, new_link, 1)

    # netif_set_up/down are also core operations on ESP32.
    data = _replace_required(
        data,
        "    netif_set_up(&ncm_obj.netif);\n    ncm_set_link(true);",
        "    MICROPY_PY_LWIP_ENTER\n"
        "    netif_set_up(&ncm_obj.netif);\n"
        "    MICROPY_PY_LWIP_EXIT\n"
        "    ncm_set_link(true);",
        "ncm_auto_init netif_set_up",
    )
    data = _replace_required(
        data,
        "                netif_set_up(&self->netif);\n                ncm_set_link(true);",
        "                MICROPY_PY_LWIP_ENTER\n"
        "                netif_set_up(&self->netif);\n"
        "                MICROPY_PY_LWIP_EXIT\n"
        "                ncm_set_link(true);",
        "active(true) netif_set_up",
    )
    data = _replace_required(
        data,
        "                ncm_set_link(false);\n                netif_set_down(&self->netif);",
        "                ncm_set_link(false);\n"
        "                MICROPY_PY_LWIP_ENTER\n"
        "                netif_set_down(&self->netif);\n"
        "                MICROPY_PY_LWIP_EXIT",
        "active(false) netif_set_down",
    )

    source.write_text(data, encoding="utf-8")
    print("Applied minimal ESP32 glue to upstream MicroPython USBD_NCM.")



def patch_upstream_ncm_ipv4_config(micropython_dir, address, netmask):
    """Replace upstream NCM's generated 169.254.x.1 address with a private LAN.

    Keep this patch intentionally narrow and semantic. MicroPython master is a
    moving target, so do not depend on surrounding comments or a whole source
    block matching byte-for-byte. We only require stable NCM symbols.

    The shared MicroPython DHCP server derives lease addresses from the first
    three octets of the NCM interface and assigns host addresses starting at
    .16, so the configured subnet must contain .16 through .23 in the same /24.
    """
    try:
        interface = ipaddress.IPv4Interface("{}/{}".format(address, netmask))
    except ValueError as exc:
        raise RuntimeError("Invalid USB NCM IPv4 configuration: {}".format(exc))

    ip = interface.ip
    network = interface.network
    rfc1918 = (
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"),
    )
    if not any(ip in private_net for private_net in rfc1918):
        raise RuntimeError(
            "USB NCM address {} is not an RFC1918 private IPv4 address".format(ip)
        )
    if ip in (network.network_address, network.broadcast_address):
        raise RuntimeError("USB NCM address {} is not a usable host address".format(ip))

    octets = [int(x) for x in str(ip).split(".")]
    lease_start = ipaddress.IPv4Address("{}.{}.{}.16".format(*octets[:3]))
    lease_end = ipaddress.IPv4Address("{}.{}.{}.23".format(*octets[:3]))
    if lease_start not in network or lease_end not in network:
        raise RuntimeError(
            "USB NCM subnet {} must contain DHCP lease range {}-{}".format(
                network, lease_start, lease_end
            )
        )

    source = micropython_dir / "extmod" / "network_usbd_ncm.c"
    data = source.read_text(encoding="utf-8")
    sentinel = "SPRINKLERS1 private USB-NCM IPv4 configuration"
    if sentinel in data:
        return

    # Insert the fixed private address immediately after upstream computes its
    # normal link-local address. The existing upstream IP packing expression
    # then consumes our overridden bytes, so we do not depend on its formatting.
    generate_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)"
        r"generate_linklocal_ip_from_mac\s*\(\s*"
        r"tud_network_mac_address\s*,\s*ip_bytes\s*\)\s*;[ \t]*$"
    )
    matches = list(generate_re.finditer(data))
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one upstream NCM link-local generator call; found {}".format(
                len(matches)
            )
        )

    match = matches[0]
    indent = match.group("indent")
    override = (
        "\n{0}// SPRINKLERS1 private USB-NCM IPv4 configuration."
        "\n{0}ip_bytes[0] = {1};"
        "\n{0}ip_bytes[1] = {2};"
        "\n{0}ip_bytes[2] = {3};"
        "\n{0}ip_bytes[3] = {4};"
    ).format(indent, octets[0], octets[1], octets[2], octets[3])
    data = data[: match.end()] + override + data[match.end() :]

    # Replace only the netmask value, tolerating comment and whitespace changes.
    netmask_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)IP\(ncm_obj\.netmask\)\.addr\s*=\s*"
        r"PP_HTONL\(\s*0x[0-9A-Fa-f]+(?:[uUlL]*)\s*\)\s*;[^\n]*$"
    )
    mask_matches = list(netmask_re.finditer(data))
    if len(mask_matches) != 1:
        raise RuntimeError(
            "Expected exactly one upstream NCM netmask assignment; found {}".format(
                len(mask_matches)
            )
        )
    mask_value = int(interface.netmask)
    data = netmask_re.sub(
        lambda m: (
            "{}IP(ncm_obj.netmask).addr = PP_HTONL(0x{:08X});  "
            "// SPRINKLERS1 {}"
        ).format(m.group("indent"), mask_value, interface.netmask),
        data,
        count=1,
    )

    # The USB link must never become a default Internet path.
    gateway_re = re.compile(
        r"(?m)^(?P<indent>[ \t]*)IP\(ncm_obj\.gateway\)\.addr\s*=\s*[^;\n]+;[^\n]*$"
    )
    gateway_matches = list(gateway_re.finditer(data))
    if len(gateway_matches) != 1:
        raise RuntimeError(
            "Expected exactly one upstream NCM gateway assignment; found {}".format(
                len(gateway_matches)
            )
        )
    data = gateway_re.sub(
        lambda m: (
            "{}IP(ncm_obj.gateway).addr = 0;  "
            "// SPRINKLERS1: USB NCM is never an Internet gateway."
        ).format(m.group("indent")),
        data,
        count=1,
    )

    source.write_text(data, encoding="utf-8")
    print(
        "Configured upstream USB NCM private LAN: {}/{} (DHCP host leases {}-{})".format(
            ip, interface.network.prefixlen, lease_start, lease_end
        )
    )

def patch_dhcpserver_guard(micropython_dir):
    source = micropython_dir / "shared" / "netutils" / "dhcpserver.c"
    data = source.read_text(encoding="utf-8")
    new = "#if MICROPY_PY_LWIP || MICROPY_PY_NETWORK_USBD_NCM_DHCP_SERVER"
    if new in data:
        return
    old = "#if MICROPY_PY_LWIP"
    if data.count(old) != 1:
        raise RuntimeError("Unexpected DHCP server compilation guard")
    source.write_text(data.replace(old, new, 1), encoding="utf-8")
    print("Enabled shared DHCP server for ESP32 upstream USBD_NCM.")


def find_firmware_bin(esp32_dir, board, variant):
    path = esp32_dir / "build-{}-{}".format(board, variant) / "firmware.bin"
    if path.is_file():
        return path
    matches = [p for p in esp32_dir.glob("build-*/firmware.bin") if board in p.parent.name]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError("MicroPython build completed but firmware.bin was not found")


def main():
    args = parse_args()
    if os.name == "nt" and not args.inside_wsl:
        return relaunch_under_wsl(args)
    if platform.system() != "Linux":
        raise RuntimeError("The ESP32 build requires Linux or WSL.")

    require_command("git", "Install git before building.")
    require_command("make", "Install build-essential before building.")
    require_command("cmake", "Install cmake before building.")

    repo_root, firmware_dir, custom_dir = get_repo_paths()
    config = load_build_config(custom_dir)
    work_dir = (
        Path(args.work_dir).expanduser().resolve()
        if args.work_dir
        else Path.home() / ".cache" / "micropython-lilygo-t-relay-s3-ncm-build"
    )
    work_dir.mkdir(parents=True, exist_ok=True)

    print("\n========================================")
    print(" MicroPython master + upstream USBD_NCM")
    print("========================================\n")
    print("Repository:      ", repo_root)
    print("Build workspace: ", work_dir)
    print("Board:           ", config["board"])
    print("Variant:         ", config["variant"])
    print("MicroPython ref: ", config["micropython_ref"])
    print("ESP-IDF ref:     ", config["esp_idf_ref"])
    print("USB NCM IPv4:    ", config.get("ncm_ipv4_address", "169.254.x.1 (upstream default)"))
    print("USB NCM netmask: ", config.get("ncm_ipv4_netmask", "255.255.0.0 (upstream default)"))

    idf_dir = ensure_esp_idf(config, work_dir, args.bootstrap)
    micropython_dir = ensure_micropython(config, work_dir)
    install_custom_board(custom_dir, micropython_dir, config["board"])

    print("MicroPython commit:", capture(["git", "rev-parse", "HEAD"], cwd=micropython_dir))

    print("\nBuilding mpy-cross...")
    run(["make", "-C", "mpy-cross"], cwd=micropython_dir)
    idf_shell(idf_dir, micropython_dir, "python -m pip install -q pyelftools ar")

    esp32_dir = micropython_dir / "ports" / "esp32"
    board_args = "BOARD={} BOARD_VARIANT={}".format(config["board"], config["variant"])

    if args.clean:
        print("\nCleaning previous ESP32 build...")
        idf_shell(idf_dir, esp32_dir, "make {} clean".format(board_args))

    print("\nPreparing ESP32 managed components...")
    idf_shell(idf_dir, esp32_dir, "make {} submodules".format(board_args))

    # Compatibility order matters: the TinyUSB API must exist before compiling
    # upstream network_usbd_ncm.c, but the MicroPython source itself is never
    # replaced with a board-specific NCM implementation.
    patch_tinyusb_descriptor_compat(micropython_dir, esp32_dir)
    patch_tinyusb_link_state_compat(esp32_dir)
    patch_esp32_upstream_ncm_port_glue(micropython_dir)
    if config.get("ncm_ipv4_address"):
        patch_upstream_ncm_ipv4_config(
            micropython_dir,
            config["ncm_ipv4_address"],
            config.get("ncm_ipv4_netmask", "255.255.255.0"),
        )
    patch_dhcpserver_guard(micropython_dir)

    print("\nBuilding MicroPython master with upstream USB NCM...")
    make_command = "make {}".format(board_args)
    if os.environ.get("CI"):
        make_command += " BUILD_VERBOSE=1"
    idf_shell(idf_dir, esp32_dir, make_command)

    firmware_bin = find_firmware_bin(esp32_dir, config["board"], config["variant"])
    output_dir = firmware_dir / "dist" / "micropython"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / config["output_filename"]
    shutil.copyfile(firmware_bin, output)

    print("\nMicroPython build successful.")
    print("Output:", output)
    print("NCM implementation: upstream extmod/network_usbd_ncm.c")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print("\nMicroPython build command failed.", file=sys.stderr)
        print("Exit code:", exc.returncode, file=sys.stderr)
        print("Command:", " ".join(str(x) for x in exc.cmd), file=sys.stderr)
        raise SystemExit(exc.returncode)
