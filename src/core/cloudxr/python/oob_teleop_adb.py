# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ADB automation for OOB teleop (``--setup-oob``): adb reverse, UDP relay lifecycle, connect, and open the headset bookmark URL."""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .oob_teleop_env import (
    DEFAULT_STREAM_SIGNALING_PORT,
    DEFAULT_WEB_CLIENT_ORIGIN,
    TETHERED_LOCAL_WEB_CLIENT,
    build_headset_bookmark_url,
    client_ui_fields_from_env,
    resolve_lan_host_for_oob,
    web_client_base_override_from_env,
)

log = logging.getLogger("oob-teleop-adb")


class OobAdbError(Exception):
    """``--setup-oob`` adb step failed; ``str(exception)`` is formatted for users (print without traceback)."""


@dataclass(frozen=True)
class AdbAutomation:
    """After WSS listens: optional ``adb connect``, ``adb reverse``, relay setup, then ``am start`` bookmark.

    * **Tethered (``tethered=True``, ``connect`` unset):** sets up ``adb reverse`` for TCP ports
      and a UDP-over-TCP relay so the headset reaches all services via ``127.0.0.1``.
    * **Wireless (``tethered=False``, ``connect`` = HOST:PORT):** ``adb connect`` + LAN URLs; set
      ``TELEOP_PROXY_HOST`` or rely on ``guess_lan_ipv4()``.
    """

    tethered: bool = False
    connect: str | None = None


def adb_automation_from_setup_oob(setup_oob: str) -> AdbAutomation:
    """``tethered`` → adb reverse + UDP relay; ``HOST:PORT`` → wireless ``adb connect`` + LAN URLs."""
    s = setup_oob.strip()
    if s.lower() == "tethered":
        return AdbAutomation(tethered=True, connect=None)
    if ":" not in s:
        raise ValueError(
            "setup_oob must be 'tethered' or HOST:PORT for wireless (e.g. 192.168.1.5:5555)"
        )
    return AdbAutomation(tethered=False, connect=s)


def parse_setup_oob_cli(value: str) -> str:
    """``argparse`` ``type=`` for ``--setup-oob`` (``tethered`` or ``HOST:PORT``)."""
    v = value.strip()
    if not v:
        raise argparse.ArgumentTypeError("--setup-oob requires 'tethered' or HOST:PORT")
    try:
        adb_automation_from_setup_oob(v)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    return "tethered" if v.lower() == "tethered" else v


def ensure_adb_connect(connect_spec: str) -> None:
    """Run plain ``adb connect`` (not ``adb -s …``)."""
    c = connect_spec.strip()
    if not c:
        return
    proc = subprocess.run(
        ["adb", "connect", c],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    out = _adb_output_text(proc)
    if proc.returncode != 0:
        log.warning("ADB connect %s failed (exit %s): %s", c, proc.returncode, out)
    else:
        log.info("ADB connect %s: %s", c, out or "ok")


def _web_client_base_for_adb_bookmark(tethered: bool = False) -> str:
    ovr = web_client_base_override_from_env()
    if ovr:
        return ovr
    if tethered:
        return TETHERED_LOCAL_WEB_CLIENT
    return DEFAULT_WEB_CLIENT_ORIGIN


def _adb_output_text(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stderr or proc.stdout or "").strip()


def adb_automation_failure_hint(diagnostic: str) -> str:
    """Human-readable next steps for common ``adb`` failures."""
    d = diagnostic.lower()
    if "unauthorized" in d:
        return (
            "Device is unauthorized: unlock the headset, confirm the USB debugging (RSA) prompt, "
            "and run `adb devices` until the device shows `device` not `unauthorized`. "
            "If this persists, try `adb kill-server` and reconnect the cable."
        )
    if (
        "no devices/emulators" in d
        or "no devices found" in d
        or "device not found" in d
    ):
        return (
            "No adb device: USB — plug in and enable debugging; wireless — run `adb connect HOST:PORT` "
            "and check `adb devices`."
        )
    if "more than one device" in d:
        return "Multiple adb devices: unplug or disconnect extras so only one headset shows in `adb devices`."
    if "offline" in d:
        return "Device offline: reconnect USB and confirm USB debugging on the headset."
    return ""


def oob_adb_automation_message(rc: int, detail: str, hint: str) -> str:
    d = detail.strip() if detail else "(no output from adb)"
    lines = [
        f"OOB adb automation failed (adb exit code {rc}).",
        "",
        d,
    ]
    if hint.strip():
        lines.extend(["", hint])
    lines.extend(
        [
            "",
            "To run the WSS proxy and OOB hub without adb, omit --setup-oob and open the teleop URL on the headset yourself.",
        ]
    )
    return "\n".join(lines)


def require_adb_on_path() -> None:
    """Raise :exc:`OobAdbError` if ``adb`` is missing."""
    if shutil.which("adb"):
        return
    raise OobAdbError(
        "Cannot use --setup-oob: `adb` was not found on PATH.\n\n"
        "Install Android Platform Tools and ensure `adb` is available, or omit --setup-oob and open "
        "the teleop bookmark URL on the headset yourself."
    )


def assert_at_most_one_adb_device() -> None:
    """Fail if more than one device is in ``device`` state (OOB adb automation targets a single device)."""
    try:
        proc = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as e:
        raise OobAdbError(
            "Cannot use --setup-oob: `adb` was not found on PATH.\n\n"
            "Install Android Platform Tools and ensure `adb` is available, or omit --setup-oob."
        ) from e
    if proc.returncode != 0:
        return
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    ready: list[str] = []
    for line in text.strip().splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "device":
            ready.append(parts[0])
    if len(ready) > 1:
        listed = ", ".join(ready)
        raise OobAdbError(
            "Too many adb devices for --setup-oob.\n\n"
            f"Currently connected: {listed}\n\n"
            "Use exactly one headset (unplug or disconnect the others), then retry. "
            "Or omit --setup-oob and open the teleop URL manually."
        )


HEADSET_RELAY_REMOTE_PATH = "/data/local/tmp/udprelay"
UDP_RELAY_TCP_PORT = 47999


def _adb_cmd_prefix() -> list[str]:
    return ["adb"]


def adb_reverse(remote_port: int, local_port: int) -> None:
    """Run ``adb reverse tcp:REMOTE tcp:LOCAL``."""
    cmd = ["adb", "reverse", f"tcp:{remote_port}", f"tcp:{local_port}"]
    log.info("adb reverse: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if proc.returncode != 0:
        raise OobAdbError(
            f"adb reverse tcp:{remote_port} tcp:{local_port} failed "
            f"(exit {proc.returncode}): {_adb_output_text(proc)}"
        )


def adb_reverse_remove_all() -> None:
    """Run ``adb reverse --remove-all`` (best-effort cleanup)."""
    proc = subprocess.run(
        ["adb", "reverse", "--remove-all"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        log.warning(
            "adb reverse --remove-all failed (exit %s): %s",
            proc.returncode,
            _adb_output_text(proc),
        )
    else:
        log.info("adb reverse --remove-all: ok")


def adb_push_file(local_path: str | Path, remote_path: str) -> None:
    """Push a local file to the device via ``adb push``."""
    cmd = ["adb", "push", str(local_path), remote_path]
    log.info("adb push: %s -> %s", local_path, remote_path)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if proc.returncode != 0:
        raise OobAdbError(
            f"adb push {local_path} {remote_path} failed "
            f"(exit {proc.returncode}): {_adb_output_text(proc)}"
        )


def adb_start_relay(remote_binary: str, udp_port: int, tcp_port: int) -> None:
    """Start the headset-side UDP relay binary in the background via ``adb shell``.

    The relay listens on UDP ``udp_port`` and tunnels to TCP ``tcp_port`` (adb-reversed to the PC).
    """
    subprocess.run(
        ["adb", "shell", "chmod", "755", remote_binary],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    cmd = [
        "adb",
        "shell",
        f"nohup {remote_binary} -udp-port {udp_port} -tcp-port {tcp_port} "
        f"</dev/null >/dev/null 2>&1 &",
    ]
    log.info("Starting headset relay: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    if proc.returncode != 0:
        raise OobAdbError(
            f"Failed to start headset relay (exit {proc.returncode}): {_adb_output_text(proc)}"
        )
    log.info("Headset relay started (UDP :%d <-> TCP :%d)", udp_port, tcp_port)


def adb_stop_relay(remote_binary: str) -> None:
    """Kill the headset-side relay process (best-effort)."""
    binary_name = Path(remote_binary).name
    proc = subprocess.run(
        ["adb", "shell", "pkill", "-f", binary_name],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode == 0:
        log.info("Headset relay stopped")
    else:
        log.debug("pkill relay (may already be gone): exit %s", proc.returncode)


def setup_adb_reverse_ports(
    proxy_port: int, relay_tcp_port: int, web_port: int | None = None
) -> list[int]:
    """Set up ``adb reverse`` for the proxy, relay tunnel, and optionally the web dev server.

    Returns the list of remote ports that were reversed (for cleanup tracking).
    """
    reversed_ports: list[int] = []
    adb_reverse(proxy_port, proxy_port)
    reversed_ports.append(proxy_port)
    adb_reverse(relay_tcp_port, relay_tcp_port)
    reversed_ports.append(relay_tcp_port)
    if web_port is not None:
        adb_reverse(web_port, web_port)
        reversed_ports.append(web_port)
    return reversed_ports


def run_adb_headset_bookmark(
    *,
    resolved_port: int,
    adb: AdbAutomation,
) -> tuple[int, str]:
    """Open the teleop bookmark URL on the headset via ``am start``.

    For **tethered** mode, uses ``127.0.0.1`` for all addresses (everything tunneled via ``adb reverse``).
    For **wireless** mode, uses the PC's LAN address.

    Returns ``(exit_code, diagnostic)``.
    """
    cmd_adb = _adb_cmd_prefix()

    if adb.tethered:
        # Signaling reaches the PC via adb reverse (127.0.0.1:port).
        # Do NOT set mediaAddress/mediaPort — WebRTC's ICE rejects loopback
        # as a remote candidate ("no local candidate").  Leave them unset so
        # the SDK negotiates media via normal ICE (typically over WiFi).
        stream_cfg: dict = {
            "serverIP": "127.0.0.1",
            "port": resolved_port,
            **client_ui_fields_from_env(),
        }
    else:
        signaling_port = int(
            os.environ.get(
                "TELEOP_STREAM_PORT", str(DEFAULT_STREAM_SIGNALING_PORT)
            ).strip()
            or DEFAULT_STREAM_SIGNALING_PORT
        )
        proxy_host = resolve_lan_host_for_oob()
        stream_cfg = {
            "serverIP": proxy_host,
            "port": signaling_port,
            **client_ui_fields_from_env(),
        }

    web_base = _web_client_base_for_adb_bookmark(tethered=adb.tethered)
    token = os.environ.get("CONTROL_TOKEN") or None
    url = build_headset_bookmark_url(
        web_client_base=web_base,
        stream_config=stream_cfg,
        control_token=token,
    )

    full = cmd_adb + [
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        shlex.quote(url),
    ]
    log.info("ADB automation: %s", " ".join(shlex.quote(c) for c in full))
    proc = subprocess.run(full, capture_output=True, text=True)
    if proc.returncode != 0:
        diag = _adb_output_text(proc)
        return proc.returncode, diag
    log.info("ADB automation: am start completed")
    return 0, ""
