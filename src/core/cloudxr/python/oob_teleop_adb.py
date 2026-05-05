# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ADB automation for OOB teleop (``--setup-oob``): open the headset bookmark URL via USB adb.

Default mode (WiFi streaming):
    The headset is connected via USB cable for adb commands only.  Streaming and
    web-page access use WiFi.  ``adb forward`` is used temporarily for CDP
    automation (DevTools socket).

USB-local mode (``--usb-local``):
    Teleop signalling and streaming travel over USB via ``adb reverse`` on the
    headset's loopback.  The headset URL uses ``serverIP=127.0.0.1`` and loads
    the WebXR client from ``https://localhost:8080`` (Python ``http.server``
    in :mod:`~.oob_teleop_env` serves the prebuilt static client over HTTPS,
    reusing the WSS proxy's PEM).  coturn runs locally and is reachable from
    the headset through adb reverse for WebRTC ICE relay.  Note: WebRTC
    requires a non-loopback interface on the headset, so WiFi must remain
    connected (no traffic traverses it).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from .oob_teleop_env import (
    DEFAULT_WEB_CLIENT_ORIGIN,
    parse_env_port,
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


def headset_non_loopback_interfaces() -> list[tuple[str, str]]:
    """Return ``(iface, ipv4)`` for each non-loopback interface with an address.

    Uses ``adb shell ip -o -4 addr show`` on the connected headset.  Returns
    an empty list when the command fails (no device, adb broken, etc.) — the
    caller decides whether that's fatal.
    """
    try:
        proc = subprocess.run(
            ["adb", "shell", "ip", "-o", "-4", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("headset_non_loopback_interfaces: %s", exc)
        return []
    if proc.returncode != 0:
        log.warning(
            "headset_non_loopback_interfaces: adb rc=%d %s",
            proc.returncode,
            (proc.stderr or proc.stdout or "").strip(),
        )
        return []
    out: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        # Example: "20: wlan0    inet 10.0.0.42/24 brd 10.0.0.255 scope global wlan0"
        parts = line.split()
        if len(parts) < 4:
            continue
        iface = parts[1]
        if iface == "lo":
            continue
        # Find the "inet <addr>/<cidr>" pair wherever it lands.
        try:
            idx = parts.index("inet")
        except ValueError:
            continue
        if idx + 1 >= len(parts):
            continue
        addr = parts[idx + 1].split("/")[0]
        out.append((iface, addr))
    return out


def require_headset_non_loopback_network() -> None:
    """Fail fast when the headset has no non-loopback IP (USB-local blocker).

    Chromium's WebRTC ``rtc::NetworkManager`` excludes loopback interfaces
    when enumerating networks for ICE.  Without at least one non-loopback
    interface with an IP, ICE gathering hangs forever (``iceGatheringState``
    stuck at ``gathering``, no candidates, no errors), and the teleop
    session fails with "No local connection candidates" (0xC0F2220F).

    The packets don't actually traverse the reported interface in USB-local
    mode — the kernel short-circuits loopback regardless of source — but
    the interface must *exist* for WebRTC's enumeration to be non-empty.
    """
    ifaces = headset_non_loopback_interfaces()
    if not ifaces:
        raise OobAdbError(
            "--usb-local: the headset has no non-loopback network interface "
            "with an IP address.\n\n"
            "Chromium's WebRTC needs at least one non-loopback interface to "
            "enumerate ICE sockets, even when all traffic routes over USB "
            "via adb reverse. Without it, ICE hangs and the session errors "
            'out with "No local connection candidates" (0xC0F2220F).\n\n'
            "Fix: connect the headset to any Wi-Fi network (it does not need "
            "internet access — a phone hotspot with no data plan works). "
            "Then retry."
        )
    log.info(
        "USB-local: headset has %d non-loopback interface(s): %s",
        len(ifaces),
        ", ".join(f"{i}={ip}" for i, ip in ifaces),
    )


def headset_wakefulness() -> str:
    """Return ``mWakefulness`` from ``adb shell dumpsys power``, or ``""`` on failure.

    Typical values: ``Awake`` | ``Asleep`` | ``Dreaming`` | ``Dozing``.
    """
    try:
        proc = subprocess.run(
            ["adb", "shell", "dumpsys", "power"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("headset_wakefulness: %s", exc)
        return ""
    if proc.returncode != 0:
        log.warning(
            "headset_wakefulness: adb rc=%d %s",
            proc.returncode,
            (proc.stderr or proc.stdout or "").strip(),
        )
        return ""
    m = re.search(r"mWakefulness=(\w+)", proc.stdout or "")
    return m.group(1) if m else ""


def assert_headset_awake(*, timeout: float = 15.0) -> None:
    """Warn-and-wait when the headset is asleep before launching OOB automation.

    Quest / PICO devices sleep when the proximity sensor is uncovered
    (e.g. the headset is sitting on a desk).  In that state, ``am start``
    may still register but the screen can return to sleep before the
    CONNECT click lands, and WebXR session entry will fail.

    Sends ``KEYCODE_WAKEUP`` once and then polls ``mWakefulness`` for up to
    ``timeout`` seconds.  Returns silently once the device is ``Awake``.
    Otherwise logs a warning and returns — downstream automation may still
    succeed if ``am start`` wakes the device.
    """
    wake = headset_wakefulness()
    if wake == "Awake":
        return

    try:
        subprocess.run(
            ["adb", "shell", "input", "keyevent", "KEYCODE_WAKEUP"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    print(
        "\n\033[33mHeadset appears to be asleep "
        f"(wakefulness={wake or '?'}).\n"
        "Please put on the headset, or cover the proximity sensor "
        "(e.g. with a piece of tape) so the device stays awake.\n"
        f"Waiting up to {timeout:.0f}s for the device to wake...\033[0m\n",
        file=sys.stderr,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1.0)
        wake = headset_wakefulness()
        if wake == "Awake":
            log.info("Headset is awake (wakefulness=%s)", wake)
            return

    log.warning(
        "Headset still appears asleep after %.0fs (wakefulness=%s); continuing anyway.",
        timeout,
        wake or "?",
    )


def adb_device_state() -> str:
    """Return ``adb get-state`` (lowercased), or ``""`` if adb is unreachable."""
    try:
        proc = subprocess.run(
            ["adb", "get-state"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    out = proc.stdout if proc.returncode == 0 else (proc.stderr or proc.stdout or "")
    return out.strip().lower()


def assert_adb_device_online() -> None:
    """Raise :exc:`OobAdbError` if the headset isn't in ``device`` state right now.

    Run before adb operations to convert a stale-preflight failure (USB
    jiggle, revoked debugging, headset reboot) into an actionable error.
    Auto-retries once via ``adb reconnect`` for transient ``offline`` —
    the most common cause is a brief USB renumeration that the daemon
    sorts out on its own when nudged.
    """
    state = adb_device_state()
    if state == "device":
        return
    # Single auto-recovery attempt for transient `offline` (USB renumeration).
    # `adb reconnect` is fast (~ms) and preserves existing reverse rules.
    if "offline" in state:
        log.warning("adb device offline — attempting `adb reconnect`")
        try:
            subprocess.run(
                ["adb", "reconnect"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        time.sleep(0.5)
        state = adb_device_state()
        if state == "device":
            log.info("adb device recovered after reconnect")
            return
    if not state:
        raise OobAdbError(
            "adb is not responding. Try `adb kill-server`, then reconnect the USB cable."
        )
    if "unauthorized" in state:
        raise OobAdbError(
            "Headset adb is unauthorized. Unlock the headset and accept the "
            "USB-debugging RSA prompt; verify with `adb devices`."
        )
    if "offline" in state:
        raise OobAdbError(
            "Headset is `offline` to adb (reconnect attempted). "
            "Reconnect the USB cable; if that doesn't help, "
            "`adb kill-server && adb start-server`."
        )
    raise OobAdbError(
        f"adb state `{state}`, expected `device`. Reconnect the USB cable."
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
    except subprocess.TimeoutExpired as e:
        raise OobAdbError(
            "adb command timed out; ensure Android Platform Tools are installed and adb is callable.\n\n"
            "Try `adb kill-server` and reconnect the USB cable, or omit --setup-oob."
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


def build_teleop_url(*, resolved_port: int, usb_local: bool = False) -> str:
    """Build the headset teleop bookmark URL for ``am start`` and CDP automation."""
    env_port = os.environ.get("TELEOP_STREAM_PORT", "").strip()
    signaling_port = (
        parse_env_port("TELEOP_STREAM_PORT", env_port) if env_port else resolved_port
    )

    if usb_local:
        from .oob_teleop_env import (  # noqa: PLC0415
            USB_HOST,
            USB_TURN_USER,
            USB_TURN_CREDENTIAL,
            usb_turn_port,
            usb_ui_port,
        )

        stream_cfg: dict = {
            "serverIP": USB_HOST,
            "port": signaling_port,
            # No mediaAddress: it's a NAT-override that bypasses ICE and would
            # short-circuit the TURN-relayed media path. Let the SDK discover
            # the media endpoint through ICE via coturn.
            "turnServer": f"turn:{USB_HOST}:{usb_turn_port()}?transport=tcp",
            "turnUsername": USB_TURN_USER,
            "turnCredential": USB_TURN_CREDENTIAL,
            "iceRelayOnly": True,
            **client_ui_fields_from_env(),
        }
        ovr = web_client_base_override_from_env()
        web_base = ovr if ovr else f"https://localhost:{usb_ui_port()}"
    else:
        stream_cfg = {
            "serverIP": resolve_lan_host_for_oob(),
            "port": signaling_port,
            **client_ui_fields_from_env(),
        }
        ovr = web_client_base_override_from_env()
        web_base = ovr if ovr else DEFAULT_WEB_CLIENT_ORIGIN

    token = os.environ.get("CONTROL_TOKEN") or None
    return build_headset_bookmark_url(
        web_client_base=web_base,
        stream_config=stream_cfg,
        control_token=token,
    )


def _adb_getprop(prop: str) -> str:
    """Read an Android system property via adb. Returns "" on failure."""
    try:
        proc = subprocess.run(
            ["adb", "shell", "getprop", prop],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("getprop %s: %s", prop, exc)
        return ""
    if proc.returncode != 0:
        log.warning(
            "getprop %s: rc=%d %s",
            prop,
            proc.returncode,
            (proc.stderr or proc.stdout or "").strip(),
        )
        return ""
    return (proc.stdout or "").strip()


def _adb_pkg_installed(package: str) -> bool:
    """Return ``True`` iff *package* is installed on the connected headset.

    Uses ``pm list packages <pkg>`` (a prefix filter) and matches the exact
    ``package:<pkg>`` line so a query for ``com.pico.browser`` doesn't
    accidentally report success when only ``com.pico.browser.overseas`` is
    present (or vice versa).
    """
    if not package:
        return False
    try:
        proc = subprocess.run(
            ["adb", "shell", "pm", "list", "packages", package],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("pm list packages %s: %s", package, exc)
        return False
    if proc.returncode != 0:
        log.warning(
            "pm list packages %s: rc=%d %s",
            package,
            proc.returncode,
            (proc.stderr or proc.stdout or "").strip(),
        )
        return False
    target = f"package:{package}"
    return any(line.strip() == target for line in (proc.stdout or "").splitlines())


def _first_installed_pkg(candidates: tuple[str, ...]) -> str | None:
    """Return the first package from *candidates* that's installed, or ``None``."""
    for pkg in candidates:
        if _adb_pkg_installed(pkg):
            return pkg
    return None


def headset_browser_package() -> str | None:
    """Return the Android package of the full-fat WebXR browser on this headset.

    WebLayer (the default VIEW-intent handler on Meta Quest + PICO) ships a
    minimal Chromium that accepts ``navigator.xr.requestSession`` but does
    not fully plumb controller input sources through to ``@react-three/xr``.
    Forcing the real vendor browser fixes controller rays and clicks.

    Resolution order:

    1. ``TELEOP_HEADSET_BROWSER_PACKAGE`` env var (explicit override; not
       validated against ``pm list packages`` — caller is trusted).
    2. Vendor map based on ``ro.product.manufacturer`` / ``ro.product.brand``,
       then probed against ``pm list packages`` so we never return a package
       that isn't actually installed:

       * Meta / Oculus → ``com.oculus.browser``.
       * PICO         → ``com.pico.browser.overseas`` (global firmware) if
         present, else ``com.pico.browser`` (domestic / China firmware).
    3. ``None`` (fall back to the generic VIEW intent).

    On current PICO firmware both browser variants are thin shells over the
    system WebLayer (same ``@weblayer_devtools_remote`` socket), so forcing
    the package does not actually escape WebLayer today.  We still target
    them for correctness and forward-compatibility with any future PICO
    build that ships an independent Chromium.
    """
    override = os.environ.get("TELEOP_HEADSET_BROWSER_PACKAGE", "").strip()
    if override:
        return override
    vendor = (
        _adb_getprop("ro.product.manufacturer") + " " + _adb_getprop("ro.product.brand")
    ).lower()
    if "meta" in vendor or "oculus" in vendor:
        # Full-fat Chromium, distinct from WebLayer — forcing it fixes WebXR
        # controller plumbing that WebLayer handles incompletely.
        return "com.oculus.browser"
    if "pico" in vendor:
        # Prefer the overseas/global package when both are installed; the
        # global firmware tends to ship the more capable Chromium build.
        # Probe via `pm list packages` so we don't try to `am start` into a
        # missing package on the wrong-region firmware.
        return _first_installed_pkg(("com.pico.browser.overseas", "com.pico.browser"))
    return None


def run_adb_headset_bookmark(
    *, resolved_port: int, usb_local: bool = False
) -> tuple[int, str]:
    """Launch the browser on the headset via ``am start`` (used when browser is not yet running).

    When a known vendor browser is detected (Meta / PICO), launches into it
    explicitly via ``-p <package>`` so the URL opens in the full Chromium
    (with working WebXR controller input), not Android WebLayer.  Falls
    back to the generic VIEW intent on unknown vendors.

    Returns ``(exit_code, diagnostic)``.
    """
    try:
        assert_adb_device_online()
    except OobAdbError as exc:
        return 99, str(exc)

    url = build_teleop_url(resolved_port=resolved_port, usb_local=usb_local)
    package = headset_browser_package()
    if package:
        log.info("ADB automation: launching into %s (bypass WebLayer)", package)
        shell_cmd = (
            f"am start -p {shlex.quote(package)} "
            f"-a android.intent.action.VIEW -d {shlex.quote(url)}"
        )
    else:
        shell_cmd = "am start -a android.intent.action.VIEW -d " + shlex.quote(url)
    full = ["adb", "shell", shell_cmd]
    redacted = " ".join(shlex.quote(c) for c in full)
    redacted = re.sub(r"(controlToken=)[^&\s'\"]+", r"\1<REDACTED>", redacted)
    log.info("ADB automation: %s", redacted)
    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as e:
        partial = (
            (e.stderr or e.stdout or b"")
            if isinstance(e.stderr or e.stdout, bytes)
            else (e.stderr or e.stdout or "")
        )
        if isinstance(partial, bytes):
            partial = partial.decode(errors="replace")
        diag = f"adb shell timed out after 30s. {partial}".strip()
        return 1, diag
    if proc.returncode != 0:
        diag = _adb_output_text(proc)
        return proc.returncode, diag
    log.info("ADB automation: am start completed")
    return 0, ""


# ---------------------------------------------------------------------------
# USB-local mode: adb reverse port-forwarding + coturn TURN relay
# ---------------------------------------------------------------------------


def setup_adb_reverse_ports() -> None:
    """Set up ``adb reverse`` for the USB-local TCP ports.

    Reverse-maps headset loopback ports to the PC so the headset can reach
    the WebXR static HTTPS server, WSS proxy, and CloudXR backend over USB.

    Ports reversed: the USB UI port (resolved via
    :func:`~.oob_teleop_env.usb_ui_port`, default 8080; override via the
    ``USB_UI_PORT`` env var) — the static HTTPS server started by
    :func:`~.oob_teleop_env.start_usb_local_https_server` — the WSS proxy
    port (resolved via :func:`~.oob_teleop_env.wss_proxy_port`), and the
    CloudXR backend port (resolved via
    :func:`~.oob_teleop_env.usb_backend_port`, default 49100; override via
    the ``USB_BACKEND_PORT`` env var).

    Raises:
        OobAdbError: device offline / unauthorized, or an ``adb reverse`` call failed.
    """
    from .oob_teleop_env import usb_backend_port, usb_ui_port, wss_proxy_port  # noqa: PLC0415

    assert_adb_device_online()
    ports = [usb_ui_port(), wss_proxy_port(), usb_backend_port()]
    for port in ports:
        try:
            subprocess.run(
                ["adb", "reverse", f"tcp:{port}", f"tcp:{port}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip() or "(no adb output)"
            raise OobAdbError(
                f"adb reverse tcp:{port} failed: {detail}. "
                "Reconnect the USB cable and verify `adb devices`."
            ) from exc
        log.info("adb reverse tcp:%d -> tcp:%d (PC)", port, port)


def teardown_adb_reverse_ports() -> None:
    """Remove the ``adb reverse`` rules set by :func:`setup_adb_reverse_ports`."""
    from .oob_teleop_env import usb_backend_port, usb_ui_port, wss_proxy_port  # noqa: PLC0415

    ports = [usb_ui_port(), wss_proxy_port(), usb_backend_port()]
    for port in ports:
        subprocess.run(
            ["adb", "reverse", "--remove", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        log.info("adb reverse removed tcp:%d", port)


def setup_adb_reverse_turn(turn_port: int) -> None:
    """Set up ``adb reverse`` for the TURN server port.

    Maps ``headset tcp:turn_port`` → ``PC tcp:turn_port`` so the headset
    browser can reach the coturn TURN server at ``127.0.0.1:turn_port``
    without WiFi.

    Raises:
        OobAdbError: device offline / unauthorized, or the ``adb reverse`` call failed.
    """
    assert_adb_device_online()
    try:
        subprocess.run(
            ["adb", "reverse", f"tcp:{turn_port}", f"tcp:{turn_port}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() or "(no adb output)"
        raise OobAdbError(
            f"adb reverse tcp:{turn_port} (TURN) failed: {detail}. "
            "Reconnect the USB cable and verify `adb devices`."
        ) from exc
    log.info("adb reverse tcp:%d (TURN) -> tcp:%d (PC coturn)", turn_port, turn_port)


def teardown_adb_reverse_turn(turn_port: int) -> None:
    """Remove the TURN ``adb reverse`` rule."""
    subprocess.run(
        ["adb", "reverse", "--remove", f"tcp:{turn_port}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    log.info("adb reverse removed tcp:%d (TURN)", turn_port)


def coturn_binary_path() -> str | None:
    """Return the path to the coturn TURN-server binary, or ``None`` if not found."""
    # Debian's `coturn` package installs `turnserver`, but some containers
    # and source builds expose `coturn` — probe both.
    for name in ("turnserver", "coturn"):
        path = shutil.which(name) or (
            f"/usr/bin/{name}" if os.path.exists(f"/usr/bin/{name}") else None
        )
        if path:
            return path
    return None


def require_coturn_available() -> None:
    """Fail fast if coturn is not installed.

    Raises :class:`OobAdbError` with install instructions when neither
    ``turnserver`` nor ``coturn`` is on PATH and not at the default
    Debian/Ubuntu location.  Call this early (before starting the
    launcher) in ``--usb-local`` mode so the user gets a clear error
    instead of a silent WebRTC-gather-timeout later.
    """
    if coturn_binary_path() is not None:
        return
    raise OobAdbError(
        "--usb-local requires coturn (TURN server) but neither `turnserver` "
        "nor `coturn` was found on PATH or in /usr/bin.\n\n"
        "Install it with:\n"
        "    sudo apt-get install -y coturn\n\n"
        "coturn runs locally (no systemd service needed — the launcher starts its "
        "own instance on port 3478 and shuts it down on exit)."
    )


def start_coturn(turn_port: int, user: str, credential: str) -> subprocess.Popen | None:
    """Start a coturn TURN server for USB-local ICE relay.

    coturn listens on ``127.0.0.1:turn_port`` (TCP + UDP).  ``adb reverse``
    exposes this port to the headset so WebRTC can obtain TURN relay
    candidates.  ``--allow-loopback-peers`` lets coturn relay between the
    headset (via adb reverse) and the CloudXR backend (UDP on PC loopback).

    Args:
        turn_port: TCP/UDP port for coturn (resolved via
            :func:`~.oob_teleop_env.usb_turn_port`, default 3478; override via
            the ``USB_TURN_PORT`` env var).
        user: TURN username.
        credential: TURN credential (password).

    Returns:
        :class:`subprocess.Popen` handle, or ``None`` if coturn failed to
        start.  Callers should treat ``None`` as non-fatal (TURN-less
        streaming may still work on LAN) but warn the operator prominently.
    """
    coturn_bin = coturn_binary_path()
    if coturn_bin is None:
        log.warning(
            "coturn: neither `turnserver` nor `coturn` on PATH — "
            "install with `sudo apt-get install coturn`"
        )
        return None

    # Write a config file — easier to maintain than a long arg list and avoids
    # shell quoting issues with special characters in credentials.
    conf_path = f"/tmp/turnserver-cloudxr-{turn_port}.conf"
    log_path = f"/tmp/coturn-cloudxr-{turn_port}.log"
    conf_content = f"""\
listening-port={turn_port}
listening-ip=127.0.0.1
external-ip=127.0.0.1
min-port=49152
max-port=49200
lt-cred-mech
fingerprint
user={user}:{credential}
realm=cloudxr
allow-loopback-peers
cli-password=cloudxr-internal
no-tls
no-dtls
no-stdout-log
log-file={log_path}
simple-log
"""
    try:
        with open(conf_path, "w") as f:
            f.write(conf_content)
    except OSError as exc:
        log.warning("coturn: failed to write config file %s: %s", conf_path, exc)
        return None

    # Truncate the log so operators only see lines from this run.
    try:
        open(log_path, "w").close()
    except OSError:
        pass

    try:
        proc = subprocess.Popen(
            [coturn_bin, "-c", conf_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        log.warning("coturn failed to start (%s): %s", coturn_bin, exc)
        return None

    # Give coturn a moment to start (or exit with a config error)
    time.sleep(0.5)
    if proc.poll() is not None:
        log.warning(
            "coturn exited immediately (exit code %d). Tail of %s:\n%s",
            proc.returncode,
            log_path,
            _tail_file(log_path, 10),
        )
        return None

    log.info(
        "coturn TURN server started (pid=%d) at 127.0.0.1:%d (log: %s)",
        proc.pid,
        turn_port,
        log_path,
    )
    return proc


def _tail_file(path: str, lines: int) -> str:
    """Return the last *lines* lines of *path* (empty string on read failure)."""
    try:
        with open(path, "r") as f:
            return "".join(f.readlines()[-lines:]).rstrip()
    except OSError:
        return ""


def stop_coturn(proc: subprocess.Popen | None) -> None:
    """Terminate the coturn process started by :func:`start_coturn`."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    log.info("coturn TURN server stopped")


# ---------------------------------------------------------------------------
# CDP automation — click the CONNECT button via Chrome DevTools Protocol
# ---------------------------------------------------------------------------

_CDP_LOCAL_PORT = 9223  # avoid clashing with any pre-existing 9222 forward


_DEVTOOLS_SOCKET_RE = re.compile(r"@([A-Za-z0-9._+-]*_devtools_remote(?:_\d+)?)")


def _discover_devtools_socket() -> str | None:
    """Return the bare name of the browser's DevTools abstract socket, or None.

    Chromium-based Android browsers expose a Unix abstract socket matching
    ``@<prefix>_devtools_remote[_<pid>]`` in ``/proc/net/unix``.  Known
    prefixes in the wild:

    * ``weblayer_devtools_remote_<pid>`` — WebLayer (Meta Quest / Pico
      default VIEW handler for some OS versions)
    * ``chrome_devtools_remote`` — full Chrome builds
    * ``com.oculus.browser_devtools_remote`` — Meta Quest Browser
    * ``<package>_devtools_remote`` — custom Chromium embedders

    This matcher accepts any of them.  If multiple candidates exist,
    WebLayer / Quest Browser sockets are preferred over generic ones (the
    teleop page is most likely to live there rather than an unrelated
    WebView from another app).
    """
    try:
        proc = subprocess.run(
            ["adb", "shell", "cat", "/proc/net/unix"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("_discover_devtools_socket: %s", exc)
        return None
    if proc.returncode != 0:
        log.warning(
            "_discover_devtools_socket: adb rc=%d %s",
            proc.returncode,
            (proc.stderr or proc.stdout or "").strip(),
        )
        return None
    candidates: list[str] = []
    for line in proc.stdout.splitlines():
        for token in line.split():
            m = _DEVTOOLS_SOCKET_RE.fullmatch(token)
            if m:
                candidates.append(m.group(1))
    if not candidates:
        return None
    # Prefer teleop-relevant prefixes in this order, otherwise fall back to
    # the first discovered socket.
    priority = ("weblayer", "com.oculus.browser", "chrome", "webview")
    for prefix in priority:
        for cand in candidates:
            if cand.startswith(prefix):
                return cand
    return candidates[0]


def _adb_forward_cdp(socket_name: str, local_port: int) -> None:
    assert_adb_device_online()
    subprocess.run(
        ["adb", "forward", f"tcp:{local_port}", f"localabstract:{socket_name}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    log.info("CDP: forwarded tcp:%d -> @%s", local_port, socket_name)


def _adb_forward_remove(local_port: int) -> None:
    subprocess.run(
        ["adb", "forward", "--remove", f"tcp:{local_port}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _cdp_list_tabs(local_port: int) -> list[dict]:
    try:
        with urllib.request.urlopen(
            f"http://localhost:{local_port}/json", timeout=3
        ) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        log.debug("CDP: failed to list tabs on port %d: %s", local_port, exc)
        return []


async def _cdp_session_click_connect(ws_url: str) -> None:
    """Open a single CDP session and click the CONNECT button.

    Handles the self-signed cert interstitial before looking for the button:

    * Primary path — ``Security.setIgnoreCertificateErrors`` + ``Page.navigate``
      (re-loads the page with cert checking disabled).
    * Fallback — DOM click-through: ``details-button`` → ``proceed-link``
      (standard Chromium cert-warning IDs).
    """
    from websockets.asyncio.client import connect as ws_connect  # already a dep

    _seq = 0

    async def send(ws, method, params=None):
        nonlocal _seq
        _seq += 1
        req_id = _seq
        await ws.send(
            json.dumps({"id": req_id, "method": method, "params": params or {}})
        )
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
            if msg.get("id") == req_id:
                return msg.get("result", {})

    async with ws_connect(ws_url) as ws:
        # ---- cert warning handling ----------------------------------------
        cert_suppressed = False
        try:
            await send(ws, "Security.setIgnoreCertificateErrors", {"ignore": True})
            cert_suppressed = True
            log.info("CDP: cert errors suppressed")
        except Exception as exc:
            log.debug(
                "CDP: Security domain unavailable (%s), will try DOM fallback", exc
            )

        # Detect interstitial: Chromium cert warning pages have #details-button
        r = await send(
            ws,
            "Runtime.evaluate",
            {
                "expression": "!!document.getElementById('details-button')",
                "returnByValue": True,
            },
        )
        on_interstitial = r.get("result", {}).get("value", False)

        if on_interstitial:
            log.info("CDP: cert interstitial detected")
            navigated = False
            if cert_suppressed:
                r2 = await send(
                    ws,
                    "Runtime.evaluate",
                    {
                        "expression": "window.location.href",
                        "returnByValue": True,
                    },
                )
                current_url = r2.get("result", {}).get("value", "")
                if current_url and not current_url.startswith("chrome-error"):
                    log.info("CDP: re-navigating to %s", current_url)
                    await send(ws, "Page.navigate", {"url": current_url})
                    await asyncio.sleep(3.0)
                    navigated = True
                else:
                    log.warning(
                        "CDP: interstitial URL is %r, falling back to DOM click-through",
                        current_url,
                    )

            if not navigated:
                await send(
                    ws,
                    "Runtime.evaluate",
                    {
                        "expression": "document.getElementById('details-button')?.click()",
                    },
                )
                await asyncio.sleep(1.5)
                await send(
                    ws,
                    "Runtime.evaluate",
                    {
                        "expression": "document.getElementById('proceed-link')?.click()",
                    },
                )
                await asyncio.sleep(3.0)

        # ---- bring tab to foreground so WebXR requestSession() succeeds ------
        # WebXR requires the page to be visible; Page.bringToFront activates the tab.
        try:
            await send(ws, "Page.bringToFront")
            log.info("CDP: tab brought to foreground")
        except Exception as exc:
            log.debug("CDP: Page.bringToFront failed (%s), continuing", exc)

        # ---- wait for #startButton to become actionable ----------------------
        # State machine returned each poll:
        #   {state: 'loading'}       — document / button not ready yet
        #   {state: 'initializing'}  — button exists but disabled (IWER +
        #                              capability checks still running)
        #   {state: 'failed', text}  — capability check set a "failed" label;
        #                              we will never be able to click, error out
        #   {state: 'ready', x, y, text, disabled}
        #                            — text === 'CONNECT' and not disabled
        _READINESS_TIMEOUT = 30.0  # capability/IWER checks can be slow
        loop = asyncio.get_running_loop()
        deadline_ready = loop.time() + _READINESS_TIMEOUT
        start_ready = loop.time()
        val: dict | None = None
        last_state: str | None = None
        while loop.time() < deadline_ready:
            r = await send(
                ws,
                "Runtime.evaluate",
                {
                    "expression": """(function() {
                    if (document.readyState !== 'complete') return {state: 'loading'};
                    const btn = document.getElementById('startButton');
                    if (!btn) return {state: 'loading'};
                    const text = btn.textContent?.trim() || '';
                    const disabled = !!btn.disabled;
                    if (text.toUpperCase().includes('FAIL')) {
                        return {state: 'failed', text, disabled};
                    }
                    if (disabled || text.toUpperCase() !== 'CONNECT') {
                        return {state: 'initializing', text, disabled};
                    }
                    const rc = btn.getBoundingClientRect();
                    return {
                        state: 'ready',
                        text, disabled,
                        x: rc.left + rc.width / 2,
                        y: rc.top + rc.height / 2,
                    };
                })()""",
                    "returnByValue": True,
                },
            )
            val = (r.get("result") or {}).get("value") or {"state": "loading"}
            state = val.get("state")
            if state != last_state:
                log.info(
                    "CDP: page state=%s text=%r disabled=%s",
                    state,
                    val.get("text"),
                    val.get("disabled"),
                )
                last_state = state
            if state == "ready":
                break
            if state == "failed":
                raise OobAdbError(
                    f"CDP: startButton marked failed (text={val.get('text')!r}). "
                    "The web client's capability check failed — inspect the headset."
                )
            await asyncio.sleep(0.5)

        if val is None or val.get("state") != "ready":
            raise OobAdbError(
                f"CDP: startButton not actionable within {_READINESS_TIMEOUT:.0f}s "
                f"(state={val.get('state') if val else 'unknown'!r}, "
                f"text={val.get('text') if val else None!r}). "
                "The page may still be initializing — check the headset."
            )

        log.info("CDP: page ready in %.1fs", loop.time() - start_ready)

        # Extra grace period: the CONNECT button can become enabled before the
        # React <XR> store is fully mounted, which causes "XR is not available"
        # errors if clicked immediately.
        await asyncio.sleep(2.0)

        # Click in two phases:
        #
        # 1. Input.dispatchMouseEvent (mousePressed + mouseReleased) — this
        #    is a *trusted* input event, so the browser grants a user-
        #    activation token (required for navigator.xr.requestSession()).
        #    PICO Browser's onClick also fires from this path, so on PICO
        #    phase 2 is effectively a no-op.
        # 2. element.click() — programmatic follow-up needed on Meta Quest
        #    Browser, where the synthesized mouse event grants activation
        #    but does not fire React's onClick handler (touch-first routing).
        #    By running inside the user-activation window opened in phase 1,
        #    requestSession() still sees activation when onClick runs.
        x, y = val["x"], val["y"]
        log.info("CDP: clicking CONNECT at (%.0f, %.0f)", x, y)
        for event_type in ("mousePressed", "mouseReleased"):
            await send(
                ws,
                "Input.dispatchMouseEvent",
                {
                    "type": event_type,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                },
            )
        # Follow-up DOM click (safety net for Quest Browser) — inside the
        # user-activation window opened by the trusted mouse events above.
        await send(
            ws,
            "Runtime.evaluate",
            {
                "expression": "document.getElementById('startButton')?.click()",
            },
        )
        log.info("CDP: CONNECT click dispatched (mouse + DOM)")

        # ---- monitor connection outcome -------------------------------------
        # DOM facts:
        #   - Button:     id="startButton", textContent "CONNECT" when idle,
        #                 changes to "DISCONNECT" / other while streaming.
        #   - Error text: id="errorMessageText" (child of the error box).
        #                 textContent is used (not innerText) so the text is
        #                 readable even when the box has display:none.
        _CONNECT_TIMEOUT = 30.0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _CONNECT_TIMEOUT
        while loop.time() < deadline:
            await asyncio.sleep(1.0)
            r = await send(
                ws,
                "Runtime.evaluate",
                {
                    "expression": """(function() {
                    const btn = document.getElementById('startButton');
                    const btnText = btn?.textContent?.trim()?.toUpperCase() || null;
                    const box = document.getElementById('errorMessageBox');
                    // Only treat as error when the box is shown with type 'error'
                    // (not 'success' or 'info' which are non-fatal status messages).
                    const isError = box?.classList?.contains('show') &&
                                   !box?.classList?.contains('success') &&
                                   !box?.classList?.contains('info');
                    const errorText = isError
                        ? (document.getElementById('errorMessageText')?.textContent?.trim() || null)
                        : null;
                    return {btnText, errorText};
                })()""",
                    "returnByValue": True,
                },
            )
            state = (r.get("result") or {}).get("value") or {}
            btn_text = state.get("btnText")
            error_text = state.get("errorText") or None

            if error_text:
                raise OobAdbError(f"Teleop connection failed: {error_text}")
            if btn_text is not None and btn_text != "CONNECT":
                log.info("CDP: start button changed to %r — session active", btn_text)
                return

        log.warning(
            "CDP: connection state unknown after %.0fs — check headset",
            _CONNECT_TIMEOUT,
        )


async def run_oob_connect(
    *, resolved_port: int, timeout: float = 60.0, usb_local: bool = False
) -> asyncio.Task | None:
    """Open the teleop page on the headset via ``am start`` and click CONNECT via CDP.

    Flow:
      1. Launch the teleop URL on the headset via ``adb shell am start``.
      2. Wait for the browser's DevTools abstract socket to appear and forward it
         (WebLayer / Meta Quest Browser / Chrome all supported).
      3. Find the teleop tab in ``/json`` (by URL content or recent navigation).
      4. Bring the tab to the foreground (required by WebXR ``requestSession``).
      5. Handle the self-signed cert interstitial if present.
      6. Find the CONNECT button and click it via ``Input.dispatchMouseEvent``.
      7. Start a background monitor that forwards mid-stream errors from the
         web client's ``errorMessageBox`` into the server log.

    Args:
        resolved_port: WSS proxy port used for signalling.
        timeout: Maximum seconds to wait for the browser/tab to appear.
        usb_local: When ``True``, the headset URL uses ``serverIP=127.0.0.1``
            and the local webxr_client dev-server at ``https://localhost:8080``.

    Returns:
        A running :class:`asyncio.Task` that monitors the headset's error
        banner and keeps the ``adb forward`` alive.  Callers should cancel
        it at shutdown (``task.cancel()``).  Returns ``None`` if the click
        phase succeeded but the monitor could not be spawned.

    Raises :exc:`OobAdbError` on any unrecoverable failure during the click
    phase; callers should treat this as non-fatal and ask the user to tap
    CONNECT manually.
    """
    deadline = time.monotonic() + timeout

    # --- Step 1: launch browser with the teleop URL --------------------------
    rc, diag = await asyncio.to_thread(
        run_adb_headset_bookmark, resolved_port=resolved_port, usb_local=usb_local
    )
    if rc != 0:
        hint = adb_automation_failure_hint(diag)
        raise OobAdbError(oob_adb_automation_message(rc, diag, hint))
    log.info("ADB: am start completed")

    # --- Step 2: wait for DevTools socket ------------------------------------
    socket_name = None
    while time.monotonic() < deadline:
        socket_name = _discover_devtools_socket()
        if socket_name:
            break
        log.info("CDP: waiting for browser DevTools socket...")
        await asyncio.sleep(2.0)

    if not socket_name:
        raise OobAdbError(
            "CDP: no *_devtools_remote abstract socket found on the headset "
            "after opening the teleop URL.\n\n"
            "Chromium-based headset browsers (WebLayer, Meta Quest Browser, "
            "Chrome) expose one when remote debugging is enabled. Check that "
            "USB debugging is authorized, the browser actually launched from "
            "`am start`, and `adb shell cat /proc/net/unix | grep devtools_remote` "
            "lists a socket."
        )
    log.info("CDP: found socket @%s", socket_name)

    try:
        _adb_forward_cdp(socket_name, _CDP_LOCAL_PORT)
    except subprocess.CalledProcessError as exc:
        raise OobAdbError(f"CDP: adb forward failed: {exc}") from exc

    try:
        # --- Step 3: find the teleop tab -------------------------------------
        # Teleop URL substrings match on the happy path.  We also accept
        # ``chrome-error://`` URLs because Chromium parks the tab there when
        # the self-signed cert is blocked — the cert-bypass in
        # ``_cdp_session_click_connect`` recovers from that state.
        def _is_candidate_tab(tab: dict) -> bool:
            url = tab.get("url") or ""
            if not tab.get("webSocketDebuggerUrl") or not url:
                return False
            return (
                "oobEnable" in url
                or "localhost" in url
                or "IsaacTeleop" in url
                or url.startswith("chrome-error://")
            )

        # Snapshot {id → url} BEFORE we look for changes so we can detect both
        # new tabs and existing tabs that were navigated to the new URL by am start.
        tabs_url_before = {
            t["id"]: (t.get("url") or "")
            for t in _cdp_list_tabs(_CDP_LOCAL_PORT)
            if "id" in t
        }
        log.info("CDP: %d tab(s) before navigation", len(tabs_url_before))

        ws_url: str | None = None
        while ws_url is None and time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            for tab in _cdp_list_tabs(_CDP_LOCAL_PORT):
                if "id" not in tab or not tab.get("webSocketDebuggerUrl"):
                    continue
                old_url = tabs_url_before.get(tab["id"])
                current_url = tab.get("url") or ""
                # Case A: brand-new tab — accept only if it looks like our page
                # (happy path) or is a cert-error page (recoverable).
                if old_url is None:
                    if not _is_candidate_tab(tab):
                        continue
                    ws_url = tab["webSocketDebuggerUrl"]
                    log.info("CDP: new tab %r url=%s", tab.get("title"), current_url)
                    break
                # Case B: existing tab whose URL changed after am start — this
                # is ours (the VIEW intent just navigated it).  Trust the diff
                # even if the new URL is chrome-error://.
                if old_url != current_url:
                    ws_url = tab["webSocketDebuggerUrl"]
                    log.info(
                        "CDP: navigated tab %r url=%s (was %s)",
                        tab.get("title"),
                        current_url,
                        old_url or "<new>",
                    )
                    break

        if ws_url is None:
            raise OobAdbError(
                "CDP: browser tab for the teleop page not found within timeout.\n"
                "The page may not have loaded — open the teleop URL on the headset manually "
                "and tap CONNECT."
            )

        # --- Step 4: cert interstitial + bring to front + readiness + click --
        # _cdp_session_click_connect polls the DOM for document.readyState +
        # #startButton (up to 10s) so no fixed page-init sleep is needed here.
        await _cdp_session_click_connect(ws_url)

        # --- Step 5: background monitor for mid-stream error banners ---------
        # Keep the adb forward alive; the monitor tears it down on exit.
        monitor_task = asyncio.create_task(
            _monitor_teleop_error_banner(ws_url, _CDP_LOCAL_PORT),
            name="cloudxr-oob-error-monitor",
        )
        return monitor_task
    except BaseException:
        # Any failure after the forward is set up but before we hand ownership
        # of it to the monitor task must clean the forward up here.
        _adb_forward_remove(_CDP_LOCAL_PORT)
        raise


async def _monitor_teleop_error_banner(ws_url: str, local_port: int) -> None:
    """Forward ``errorMessageBox`` content from the web client into the server log.

    Opens its own CDP session and polls the DOM once per second, logging at
    WARNING level whenever the error banner shows new text with class
    ``error`` (not ``success``/``info``, which are non-fatal status messages).
    De-dupes identical messages so a banner that remains displayed logs once.

    Runs until the task is cancelled (normal shutdown) or the WebSocket
    drops (tab closed / headset disconnected).  Always tears down the
    ``adb forward`` on exit.
    """
    from websockets.asyncio.client import connect as ws_connect  # noqa: PLC0415

    _seq = 0
    last_banner = ""

    async def send(ws, method: str, params: dict | None = None) -> dict:
        nonlocal _seq
        _seq += 1
        req_id = _seq
        await ws.send(
            json.dumps({"id": req_id, "method": method, "params": params or {}})
        )
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
            if msg.get("id") == req_id:
                return msg.get("result", {})

    try:
        async with ws_connect(ws_url) as ws:
            # Keep errors suppressed so the tab never stops rendering because of
            # a stray cert hiccup on a later navigation.
            try:
                await send(ws, "Security.setIgnoreCertificateErrors", {"ignore": True})
            except Exception as exc:
                log.debug("monitor: Security domain unavailable (%s)", exc)
            log.info("monitor: tracking errorMessageBox on the teleop page")
            while True:
                await asyncio.sleep(1.0)
                r = await send(
                    ws,
                    "Runtime.evaluate",
                    {
                        "expression": """(function() {
                            const box = document.getElementById('errorMessageBox');
                            if (!box || !box.classList.contains('show')) return '';
                            if (box.classList.contains('success') ||
                                box.classList.contains('info')) return '';
                            return document.getElementById('errorMessageText')
                                       ?.textContent?.trim() || '';
                        })()""",
                        "returnByValue": True,
                    },
                )
                banner = (r.get("result") or {}).get("value") or ""
                if banner and banner != last_banner:
                    log.warning("Teleop client error: %s", banner)
                    # Mirror to stderr so the operator sees mid-stream errors
                    # in the console, not only in the server log file.
                    print(
                        f"\n\033[33mTeleop client error: {banner}\033[0m\n",
                        file=sys.stderr,
                        flush=True,
                    )
                last_banner = banner
    except asyncio.CancelledError:
        log.info("monitor: cancelled")
        raise
    except Exception as exc:
        # WS drop, CDP error, etc. — expected at tab close; log and exit quietly.
        log.info("monitor: exiting (%s)", exc)
    finally:
        _adb_forward_remove(local_port)
