#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
"""Probe the Quick Start browser client through CDP and OOB hub state.

This is the desktop-browser validation layer for the Quick Start workflow:

1. Launch Chromium/Chrome against the locally hosted web client.
2. Click CONNECT through Chrome DevTools Protocol.
3. Poll the WSS proxy's OOB state endpoint until the client reports
   connected streaming state. Metrics are recorded when available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class ProbeError(RuntimeError):
    """Raised when the browser client cannot prove the expected signal."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-url", required=True, help="Hosted web client URL")
    parser.add_argument(
        "--state-url",
        required=True,
        help="OOB state endpoint, for example https://127.0.0.1:48322/api/oob/v1/state",
    )
    parser.add_argument(
        "--browser",
        default=None,
        help=(
            "Chromium/Chrome executable. Defaults to QUICK_START_E2E_BROWSER "
            "or PATH lookup."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Seconds to wait for browser connection and OOB state.",
    )
    parser.add_argument(
        "--require-metrics",
        action="store_true",
        help="Require the OOB streaming state to include non-empty metrics.",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Optional file to write the last successful OOB state snapshot.",
    )
    return parser.parse_args()


def find_browser(explicit: str | None) -> str:
    if explicit:
        return explicit
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "msedge",
    ):
        path = shutil.which(name)
        if path:
            return path
    raise ProbeError(
        "No Chromium-based browser found. Set QUICK_START_E2E_BROWSER to the "
        "Chrome/Chromium executable on this runner."
    )


def read_json(url: str, *, ssl_context: ssl.SSLContext | None = None) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": "quick-start-client-probe"}
    )
    with urllib.request.urlopen(request, timeout=5.0, context=ssl_context) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_devtools_port(
    user_data_dir: Path, proc: subprocess.Popen, timeout: float
) -> int:
    active_port_file = user_data_dir / "DevToolsActivePort"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise ProbeError(
                f"Browser exited before DevTools became ready (rc={proc.returncode})"
            )
        if active_port_file.exists():
            lines = active_port_file.read_text(encoding="utf-8").splitlines()
            if lines:
                return int(lines[0])
        time.sleep(0.25)
    raise ProbeError("Timed out waiting for Chrome DevToolsActivePort")


def find_client_tab(devtools_port: int, client_url: str, timeout: float) -> str:
    expected = urllib.parse.urlparse(client_url)
    deadline = time.monotonic() + timeout
    last_tabs: Any = None
    while time.monotonic() < deadline:
        tabs = read_json(f"http://127.0.0.1:{devtools_port}/json/list")
        last_tabs = tabs
        for tab in tabs:
            ws_url = tab.get("webSocketDebuggerUrl")
            current_url = tab.get("url") or ""
            parsed = urllib.parse.urlparse(current_url)
            if not ws_url:
                continue
            if parsed.scheme == expected.scheme and parsed.netloc == expected.netloc:
                return ws_url
            if current_url.startswith("chrome-error://"):
                return ws_url
        time.sleep(0.5)
    raise ProbeError(
        f"Could not find hosted client tab in DevTools list: {last_tabs!r}"
    )


async def cdp_click_connect(ws_url: str, timeout: float) -> None:
    from websockets.asyncio.client import connect as ws_connect

    next_id = 0

    async def send(
        ws, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        nonlocal next_id
        next_id += 1
        await ws.send(
            json.dumps({"id": next_id, "method": method, "params": params or {}})
        )
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == next_id:
                if "error" in msg:
                    raise ProbeError(f"CDP {method} failed: {msg['error']}")
                return msg

    async with ws_connect(ws_url) as ws:
        for method, params in (
            ("Page.enable", None),
            ("Runtime.enable", None),
            ("Security.enable", None),
            ("Security.setIgnoreCertificateErrors", {"ignore": True}),
        ):
            try:
                await send(ws, method, params)
            except ProbeError:
                if method.startswith("Security."):
                    continue
                raise

        await send(ws, "Page.bringToFront")
        deadline = time.monotonic() + timeout
        last_state: Any = None
        while time.monotonic() < deadline:
            result = await send(
                ws,
                "Runtime.evaluate",
                {
                    "expression": """(() => {
                        const btn = document.getElementById('startButton');
                        const errorNode = document.getElementById('errorMessageText');
                        const errorText = errorNode?.textContent?.trim() || '';
                        if (!btn) return {state: 'loading', errorText};
                        const text = btn.textContent?.trim() || '';
                        const disabled = Boolean(btn.disabled);
                        if (text.toUpperCase().includes('FAIL')) {
                            return {state: 'failed', text, disabled, errorText};
                        }
                        if (disabled || text.toUpperCase() !== 'CONNECT') {
                            return {state: 'initializing', text, disabled, errorText};
                        }
                        const rc = btn.getBoundingClientRect();
                        return {
                            state: 'ready',
                            text,
                            disabled,
                            x: rc.left + rc.width / 2,
                            y: rc.top + rc.height / 2,
                            errorText,
                        };
                    })()""",
                    "returnByValue": True,
                },
            )
            value = (result.get("result") or {}).get("result", {}).get("value") or {}
            last_state = value
            if value.get("state") == "ready":
                x = float(value["x"])
                y = float(value["y"])
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
                await send(
                    ws,
                    "Runtime.evaluate",
                    {
                        "expression": "document.getElementById('startButton')?.click()",
                        "userGesture": True,
                    },
                )
                await asyncio.sleep(1.0)
                diagnostic = await send(
                    ws,
                    "Runtime.evaluate",
                    {
                        "expression": """(() => {
                            const byId = (id) => document.getElementById(id);
                            return {
                                buttonText: byId('startButton')?.textContent?.trim() || '',
                                buttonDisabled: Boolean(byId('startButton')?.disabled),
                                errorText: byId('errorMessageText')?.textContent?.trim() || '',
                                errorClass: byId('errorMessageBox')?.className || '',
                                serverIP: byId('serverIpInput')?.value || '',
                                port: byId('portInput')?.value || '',
                                headless: Boolean(byId('cloudxrHeadless')?.checked),
                                href: window.location.href,
                            };
                        })()""",
                        "returnByValue": True,
                    },
                )
                value = (diagnostic.get("result") or {}).get("result", {}).get("value")
                print(
                    "Page diagnostic after CONNECT: "
                    + json.dumps(value, sort_keys=True),
                    flush=True,
                )
                return
            if value.get("state") == "failed":
                raise ProbeError(f"Client capability check failed: {value!r}")
            await asyncio.sleep(0.5)

    raise ProbeError(f"CONNECT did not become actionable: {last_state!r}")


def wait_for_streaming_state(
    state_url: str,
    *,
    timeout: float,
    ssl_context: ssl.SSLContext,
    require_metrics: bool,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state: Any = None
    while time.monotonic() < deadline:
        try:
            state = read_json(state_url, ssl_context=ssl_context)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_state = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0)
            continue

        last_state = state
        for headset in state.get("headsets", []):
            if not headset.get("connected") or not headset.get("streaming"):
                continue
            metrics = headset.get("metricsByCadence") or {}
            has_metrics = any(
                (entry.get("metrics") or {}) for entry in metrics.values()
            )
            headset["metricsObserved"] = has_metrics
            if has_metrics or not require_metrics:
                return state
        time.sleep(1.0)

    expectation = (
        "streaming client metrics" if require_metrics else "streaming client state"
    )
    raise ProbeError(f"Timed out waiting for {expectation}. Last state: {last_state!r}")


def main() -> int:
    args = parse_args()
    browser = find_browser(args.browser)
    ssl_context = ssl._create_unverified_context()

    with tempfile.TemporaryDirectory(prefix="quick-start-client-") as tmp:
        user_data_dir = Path(tmp) / "profile"
        user_data_dir.mkdir()
        proc = subprocess.Popen(
            [
                browser,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--ignore-gpu-blocklist",
                "--enable-webgl",
                "--enable-webgl2",
                "--use-gl=swiftshader",
                "--enable-unsafe-swiftshader",
                "--ignore-certificate-errors",
                "--allow-insecure-localhost",
                "--remote-debugging-port=0",
                f"--user-data-dir={user_data_dir}",
                args.client_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        try:
            devtools_port = wait_for_devtools_port(user_data_dir, proc, args.timeout)
            ws_url = find_client_tab(devtools_port, args.client_url, args.timeout)
            asyncio.run(cdp_click_connect(ws_url, args.timeout))
            state = wait_for_streaming_state(
                args.state_url,
                timeout=args.timeout,
                ssl_context=ssl_context,
                require_metrics=args.require_metrics,
            )
            if args.summary_json:
                args.summary_json.parent.mkdir(parents=True, exist_ok=True)
                args.summary_json.write_text(
                    json.dumps(state, indent=2), encoding="utf-8"
                )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

    print("Quick Start client probe passed: streaming client state observed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeError as exc:
        print(f"quick_start_client_probe.py: error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
