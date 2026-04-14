# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ADB automation for OOB teleop (``--setup-oob``): open the headset bookmark URL via USB adb.

The headset is connected via USB cable for adb commands only.  Streaming and
web-page access use WiFi.  ``adb forward`` is used temporarily for CDP
automation (DevTools socket); no ``adb reverse`` or USB tethering.
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


def run_adb_headset_bookmark(*, resolved_port: int) -> tuple[int, str]:
    """Open the teleop bookmark URL on the headset via ``am start``.

    Uses the PC's LAN address — the headset reaches the proxy over WiFi.
    ``resolved_port`` is used as the stream port unless ``TELEOP_STREAM_PORT``
    is set explicitly.  Returns ``(exit_code, diagnostic)``.
    """
    env_port = os.environ.get("TELEOP_STREAM_PORT", "").strip()
    signaling_port = (
        parse_env_port("TELEOP_STREAM_PORT", env_port) if env_port else resolved_port
    )
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
# CDP automation — click the CONNECT button via Chrome DevTools Protocol
# ---------------------------------------------------------------------------

_CDP_LOCAL_PORT = 9223  # avoid clashing with any pre-existing 9222 forward


def _discover_devtools_socket() -> str | None:
    """Return the bare name of the browser's DevTools abstract socket, or None.

    Pico Browser (WebLayer/Chromium) exposes a socket like
    ``@weblayer_devtools_remote_<pid>`` in ``/proc/net/unix``.
    The PID suffix changes every time the browser starts.
    """
    try:
        proc = subprocess.run(
            ["adb", "shell", "cat", "/proc/net/unix"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in proc.stdout.splitlines():
        if "weblayer_devtools_remote" in line:
            for token in line.split():
                if token.startswith("@weblayer_devtools_remote"):
                    return token[1:]  # strip leading @
    return None


def _adb_forward_cdp(socket_name: str, local_port: int) -> None:
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

        # ---- find CONNECT button with retries --------------------------------
        val: dict = {}
        for attempt in range(1, 4):
            r = await send(
                ws,
                "Runtime.evaluate",
                {
                    "expression": """(function() {
                    const btn = Array.from(document.querySelectorAll('button,[role=button]'))
                        .find(e => e.textContent.trim().toUpperCase() === 'CONNECT');
                    if (!btn) return {found: false};
                    const rc = btn.getBoundingClientRect();
                    return {found: true, x: rc.left + rc.width / 2, y: rc.top + rc.height / 2};
                })()""",
                    "returnByValue": True,
                },
            )
            val = (r.get("result") or {}).get("value") or {}
            if val.get("found"):
                break
            log.info("CDP: CONNECT button not found yet (attempt %d/3)", attempt)
            if attempt < 3:
                await asyncio.sleep(2.0)

        if not val.get("found"):
            raise OobAdbError(
                "CDP: CONNECT button not found on the teleop page.\n"
                "The page may not have finished loading — check the headset."
            )

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
        log.info("CDP: CONNECT click dispatched")

        # ---- monitor connection outcome -------------------------------------
        # DOM facts learned from page inspection:
        #   - Start/stop button: id="startButton", text "CONNECT" when idle
        #   - Error box: first [role=alert] is empty validation-message-box;
        #     error text lives in the *second* [role=alert] (error-message-box)
        _CONNECT_TIMEOUT = 30.0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _CONNECT_TIMEOUT
        while loop.time() < deadline:
            await asyncio.sleep(2.0)
            r = await send(
                ws,
                "Runtime.evaluate",
                {
                    "expression": """(function() {
                    const alertText = Array.from(document.querySelectorAll('[role=alert]'))
                        .map(e => e.innerText?.trim()).find(t => !!t) || null;
                    const btn = document.getElementById('startButton');
                    const btnText = btn?.textContent?.trim()?.toUpperCase() || null;
                    return {alertText, btnText};
                })()""",
                    "returnByValue": True,
                },
            )
            state = (r.get("result") or {}).get("value") or {}
            btn_text = state.get("btnText")
            if btn_text is not None and btn_text != "CONNECT":
                log.info("CDP: start button changed to %r — session active", btn_text)
                return
            if state.get("alertText"):
                raise OobAdbError(f"Teleop connection failed: {state['alertText']}")
        log.warning(
            "CDP: connection state unknown after %.0fs — check headset",
            _CONNECT_TIMEOUT,
        )


async def run_oob_connect(*, resolved_port: int, timeout: float = 60.0) -> None:
    """Open the teleop page on the headset and click CONNECT via CDP.

    Combines the ``am start`` bookmark step with CDP automation so that the
    new tab can be identified unambiguously by diffing tab IDs before and after
    ``am start`` — regardless of how many other tabs are already open.

    Flow:
      1. Discover the Pico Browser DevTools abstract socket and forward it.
      2. Snapshot existing tab IDs.
      3. Run ``am start`` to open the teleop bookmark URL.
      4. Wait for a new tab (ID not in snapshot) to appear.
      5. Handle self-signed cert interstitial if present.
      6. Find the CONNECT button and click it via ``Input.dispatchMouseEvent``.
      7. Clean up the ``adb forward``.

    Raises :exc:`OobAdbError` on any unrecoverable failure; callers should
    treat this as non-fatal and ask the user to tap CONNECT manually.
    """
    deadline = time.monotonic() + timeout

    # --- DevTools socket discovery -------------------------------------------
    socket_name = _discover_devtools_socket()
    if not socket_name:
        raise OobAdbError(
            "CDP: Pico Browser DevTools socket not found.\n"
            "Ensure the browser is open on the headset, then retry or tap CONNECT manually."
        )
    log.info("CDP: found socket @%s", socket_name)

    try:
        _adb_forward_cdp(socket_name, _CDP_LOCAL_PORT)
    except subprocess.CalledProcessError as exc:
        raise OobAdbError(f"CDP: adb forward failed: {exc}") from exc

    try:
        # --- snapshot existing tabs before am start --------------------------
        tabs_before = {t["id"] for t in _cdp_list_tabs(_CDP_LOCAL_PORT) if "id" in t}
        log.info("CDP: %d tab(s) open before am start", len(tabs_before))

        # --- open URL on headset ---------------------------------------------
        rc, diag = await asyncio.to_thread(
            run_adb_headset_bookmark, resolved_port=resolved_port
        )
        if rc != 0:
            hint = adb_automation_failure_hint(diag)
            raise OobAdbError(oob_adb_automation_message(rc, diag, hint))
        log.info("ADB: am start completed; waiting for new tab")

        # --- wait for the newly opened tab (not in pre-snapshot) -------------
        ws_url: str | None = None
        while time.monotonic() < deadline:
            for tab in _cdp_list_tabs(_CDP_LOCAL_PORT):
                if "id" not in tab:
                    continue
                if tab["id"] not in tabs_before and tab.get("webSocketDebuggerUrl"):
                    ws_url = tab["webSocketDebuggerUrl"]
                    log.info("CDP: new tab %r url=%s", tab.get("title"), tab.get("url"))
                    break
            if ws_url:
                break
            await asyncio.sleep(1.0)

        if ws_url is None:
            raise OobAdbError(
                "CDP: new browser tab not found within timeout.\n"
                "The browser may not have opened the teleop page — tap CONNECT manually."
            )

        # Give the page JS time to finish initializing before we interact with it
        log.info("CDP: waiting for page to initialize...")
        await asyncio.sleep(4.0)

        # --- cert interstitial + CONNECT click --------------------------------
        await _cdp_session_click_connect(ws_url)
    finally:
        _adb_forward_remove(_CDP_LOCAL_PORT)
