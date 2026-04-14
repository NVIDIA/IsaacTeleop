# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OOB teleop environment: proxy port, LAN detection, stream defaults, headset bookmark URLs, startup banner."""

from __future__ import annotations

import os
import socket
from urllib.parse import urlencode

from .oob_teleop_hub import OOB_WS_PATH

WSS_PROXY_DEFAULT_PORT = 48322

DEFAULT_WEB_CLIENT_ORIGIN = "https://nvidia.github.io/IsaacTeleop/client/"

TELEOP_WEB_CLIENT_BASE_ENV = "TELEOP_WEB_CLIENT_BASE"

CHROME_INSPECT_DEVICES_URL = "chrome://inspect/#devices"


def web_client_base_override_from_env() -> str | None:
    v = os.environ.get(TELEOP_WEB_CLIENT_BASE_ENV, "").strip()
    return v or None


def parse_env_port(env_var: str, raw: str) -> int:
    """Parse and validate a port string from an environment variable."""
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(
            f"{env_var}={raw!r} is not a valid integer; "
            f"set it to a port number (1–65535) or unset it to use the default."
        ) from None
    if not 1 <= port <= 65535:
        raise ValueError(f"{env_var}={port} is out of range; must be 1–65535.")
    return port


def wss_proxy_port() -> int:
    """TCP port for the WSS proxy (``PROXY_PORT`` environment variable if set, else ``48322``)."""
    raw = os.environ.get("PROXY_PORT", "").strip()
    if raw:
        return parse_env_port("PROXY_PORT", raw)
    return WSS_PROXY_DEFAULT_PORT


def guess_lan_ipv4() -> str | None:
    """Best-effort LAN IPv4 for operator URLs when headsets reach the PC by IP."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.25)
            s.connect(("192.0.2.1", 1))
            addr, _ = s.getsockname()
    except OSError:
        return None
    if not addr or addr == "127.0.0.1":
        return None
    return addr


def default_initial_stream_config(resolved_proxy_port: int) -> dict:
    """Default hub stream config from env and LAN guess (same host as proxy port by default)."""
    env_ip = os.environ.get("TELEOP_STREAM_SERVER_IP", "").strip()
    env_port = os.environ.get("TELEOP_STREAM_PORT", "").strip()
    server_ip = env_ip or guess_lan_ipv4() or "127.0.0.1"
    port = (
        parse_env_port("TELEOP_STREAM_PORT", env_port)
        if env_port
        else resolved_proxy_port
    )
    return {"serverIP": server_ip, "port": port}


def client_ui_fields_from_env() -> dict:
    """Optional WebXR client UI defaults merged into hub ``config`` and bookmarks.

    Keys match query params the WebXR client reads on page load
    (``serverIP``, ``port``, ``codec``, ``panelHiddenAtStart``).
    """
    out: dict = {}
    codec = os.environ.get("TELEOP_CLIENT_CODEC", "").strip()
    if codec:
        out["codec"] = codec
    ph = os.environ.get("TELEOP_CLIENT_PANEL_HIDDEN_AT_START", "").strip().lower()
    if ph in ("1", "true", "yes", "on"):
        out["panelHiddenAtStart"] = True
    elif ph in ("0", "false", "no", "off"):
        out["panelHiddenAtStart"] = False
    return out


def build_headset_bookmark_url(
    *,
    web_client_base: str,
    stream_config: dict | None = None,
    control_token: str | None = None,
) -> str:
    """Full WebXR page URL with OOB query params (``oobEnable=1``, stream fields, optional token).

    The client derives ``wss://{serverIP}:{port}/oob/v1/ws`` from ``serverIP`` + ``port`` in the query
    when ``oobEnable=1``.
    """
    cfg = stream_config or {}
    if not cfg.get("serverIP") or cfg.get("port") is None:
        raise ValueError(
            "build_headset_bookmark_url requires stream_config with serverIP and port"
        )
    params: dict[str, str] = {"oobEnable": "1"}
    if control_token:
        params["controlToken"] = control_token
    params["serverIP"] = str(cfg["serverIP"])
    params["port"] = str(int(cfg["port"]))
    v = cfg.get("codec")
    if v is not None and str(v).strip() != "":
        params["codec"] = str(v).strip()
    v = cfg.get("panelHiddenAtStart")
    if isinstance(v, bool):
        params["panelHiddenAtStart"] = "true" if v else "false"
    q = urlencode(params)
    base = web_client_base.rstrip("/")
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{q}"


def resolve_lan_host_for_oob() -> str:
    """PC LAN address the headset uses for ``wss://…:PROXY_PORT`` over WiFi."""
    h = os.environ.get("TELEOP_PROXY_HOST", "").strip() or guess_lan_ipv4()
    if not h:
        raise RuntimeError(
            "--setup-oob needs this PC's LAN IP for WebXR/WSS URLs. "
            "Set TELEOP_PROXY_HOST to an address the headset can reach over WiFi "
            "(or fix routing so guess_lan_ipv4() works)."
        )
    return h


def print_oob_hub_startup_banner(*, lan_host: str | None = None) -> None:
    """Print operator instructions for OOB + USB adb automation."""
    port = wss_proxy_port()
    token = os.environ.get("CONTROL_TOKEN") or None

    if not lan_host:
        lan_host = resolve_lan_host_for_oob()
    primary_host = lan_host

    web_base = DEFAULT_WEB_CLIENT_ORIGIN
    stream_cfg = default_initial_stream_config(port)
    stream_cfg = {**stream_cfg, "serverIP": primary_host}

    web_client_base_override = web_client_base_override_from_env()
    if web_client_base_override:
        web_base = web_client_base_override

    stream_cfg = {**stream_cfg, **client_ui_fields_from_env()}

    primary_base = f"https://{primary_host}:{port}"
    bookmark_display = build_headset_bookmark_url(
        web_client_base=web_base,
        stream_config=stream_cfg,
        control_token=None,
    )
    if token:
        bookmark_display += "&controlToken=<REDACTED>"
    wss_primary = f"wss://{primary_host}:{port}{OOB_WS_PATH}"

    bar = "=" * 72
    print(bar)
    print("OOB TELEOP — enabled (out-of-band control hub is running in this WSS proxy)")
    print(bar)
    print()
    print(
        f"  The hub shares the CloudXR proxy TLS port {port} on this machine "
        f"(control WebSocket: {wss_primary})."
    )
    print(
        "  Same steps as docs: references/oob_teleop_control.rst — "
        '"End-to-end workflow (the usual path)".'
    )
    print()
    print(
        "  adb: USB cable — headset connected via USB for adb; streaming and web page over WiFi."
    )
    print()
    print("  Step 1 — Open teleop page on headset (adb)")
    print(
        '           After "WSS proxy listening on port …", `--setup-oob` runs '
        "`adb` to open the page on the headset. If that fails, open this URL manually:"
    )
    print(f"           {bookmark_display}")
    if web_client_base_override:
        print(
            f"           ({TELEOP_WEB_CLIENT_BASE_ENV} overrides the WebXR origin; "
            "query still targets this streaming host.)"
        )
    print()
    print("  Step 2 — Accept cert + click CONNECT (CDP automation)")
    print("           CDP automation will accept the self-signed certificate and click")
    print("           CONNECT automatically via Chrome DevTools Protocol.")
    print(
        "           If it fails, fall back to manual: open "
        f"{CHROME_INSPECT_DEVICES_URL},"
    )
    print("           inspect the headset tab, and click CONNECT in DevTools.")
    print()
    print("-" * 72)
    print("OOB HTTP (optional — operators / curl / scripts on this PC)")
    print("-" * 72)
    cfg_q = urlencode(
        {
            "serverIP": str(stream_cfg["serverIP"]),
            "port": str(int(stream_cfg["port"])),
        }
    )
    print(f"  State:  {primary_base}/api/oob/v1/state")
    print(f"  Config: {primary_base}/api/oob/v1/config?{cfg_q}")
    if token:
        print()
        print(
            "  CONTROL_TOKEN is set: add ?token=... or header X-Control-Token on OOB HTTP requests."
        )
    print(bar)
    print()
