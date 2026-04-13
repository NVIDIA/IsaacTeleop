# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ADB automation for OOB teleop (``--setup-oob``): open the headset bookmark URL via USB adb.

The headset is connected via USB cable for adb commands only.  Streaming and
web-page access use WiFi — no ``adb reverse`` or USB tethering.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess

from .oob_teleop_env import (
    DEFAULT_WEB_CLIENT_ORIGIN,
    build_headset_bookmark_url,
    client_ui_fields_from_env,
    resolve_lan_host_for_oob,
    web_client_base_override_from_env,
)

log = logging.getLogger("oob-teleop-adb")


class OobAdbError(Exception):
    """``--setup-oob`` adb step failed; ``str(exception)`` is formatted for users (print without traceback)."""


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
            "No adb device: plug in the USB cable, enable USB debugging on the headset, "
            "and check `adb devices`."
        )
    if "more than one device" in d:
        return "Multiple adb devices: unplug extras so only one headset shows in `adb devices`."
    if "offline" in d:
        return "Device offline: reconnect the USB cable and confirm USB debugging on the headset."
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


def assert_exactly_one_adb_device() -> None:
    """Fail unless exactly one device is in ``device`` state."""
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
        diag = _adb_output_text(proc)
        raise OobAdbError(
            f"adb devices failed (exit code {proc.returncode}).\n\n"
            f"{diag}\n\n"
            "Check your adb installation and USB connection."
        )
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    ready: list[str] = []
    for line in text.strip().splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "device":
            ready.append(parts[0])
    if len(ready) == 0:
        raise OobAdbError(
            "No adb device found for --setup-oob.\n\n"
            "Plug in the USB cable, enable USB debugging on the headset, and check `adb devices`. "
            "Or omit --setup-oob and open the teleop URL on the headset yourself."
        )
    if len(ready) > 1:
        listed = ", ".join(ready)
        raise OobAdbError(
            "Too many adb devices for --setup-oob.\n\n"
            f"Currently connected: {listed}\n\n"
            "Unplug extras so only one headset is connected, then retry. "
            "Or omit --setup-oob and open the teleop URL manually."
        )


def run_adb_headset_bookmark(*, resolved_port: int) -> tuple[int, str]:
    """Open the teleop bookmark URL on the headset via ``am start``.

    Uses the PC's LAN address — the headset reaches the proxy over WiFi.
    ``resolved_port`` is used as the stream port unless ``TELEOP_STREAM_PORT``
    is set explicitly.  Returns ``(exit_code, diagnostic)``.
    """
    env_port = os.environ.get("TELEOP_STREAM_PORT", "").strip()
    signaling_port = int(env_port) if env_port else resolved_port
    proxy_host = resolve_lan_host_for_oob()
    stream_cfg: dict = {
        "serverIP": proxy_host,
        "port": signaling_port,
        **client_ui_fields_from_env(),
    }

    ovr = web_client_base_override_from_env()
    web_base = ovr if ovr else DEFAULT_WEB_CLIENT_ORIGIN
    token = os.environ.get("CONTROL_TOKEN") or None
    url = build_headset_bookmark_url(
        web_client_base=web_base,
        stream_config=stream_cfg,
        control_token=token,
    )

    shell_cmd = "am start -a android.intent.action.VIEW -d " + shlex.quote(url)
    full = ["adb", "shell", shell_cmd]
    log.info("ADB automation: %s", " ".join(shlex.quote(c) for c in full))
    proc = subprocess.run(full, capture_output=True, text=True)
    if proc.returncode != 0:
        diag = _adb_output_text(proc)
        return proc.returncode, diag
    log.info("ADB automation: am start completed")
    return 0, ""
