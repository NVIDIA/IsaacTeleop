# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OOB teleop environment: proxy port, LAN detection, stream defaults, headset bookmark URLs, startup banner."""

from __future__ import annotations

import logging
import os
import socket
from urllib.parse import urlencode

from .oob_teleop_hub import OOB_WS_PATH

log = logging.getLogger("oob-teleop-env")

WSS_PROXY_DEFAULT_PORT = 48322

# Hosted WebXR client used by default for OOB bookmark URLs (wireless mode).
DEFAULT_WEB_CLIENT_ORIGIN = "https://nvidia.github.io/IsaacTeleop/client/"

# Local web client served via webpack dev-server, reached through adb reverse in tethered mode.
TETHERED_LOCAL_WEB_CLIENT = "https://127.0.0.1:8080/"

# Optional override for the WebXR page origin in OOB bookmark URLs.
TELEOP_WEB_CLIENT_BASE_ENV = "TELEOP_WEB_CLIENT_BASE"

# CloudXR runtime signaling (WebSocket) TCP port.
DEFAULT_STREAM_SIGNALING_PORT = 49100

# CloudXR media (RTP) default UDP port on host.
DEFAULT_STREAM_MEDIA_UDP_PORT = 47998

CHROME_INSPECT_DEVICES_URL = "chrome://inspect/#devices"


def web_client_base_override_from_env() -> str | None:
    v = os.environ.get(TELEOP_WEB_CLIENT_BASE_ENV, "").strip()
    return v or None


def wss_proxy_port() -> int:
    """TCP port for the WSS proxy (``PROXY_PORT`` environment variable if set, else ``48322``)."""
    raw = os.environ.get("PROXY_PORT", "").strip()
    if raw:
        return int(raw)
    return WSS_PROXY_DEFAULT_PORT


def guess_lan_ipv4() -> str | None:
    """Best-effort LAN IPv4 for operator URLs when headsets reach the PC by IP."""
    # Any non-loopback destination works: UDP "connect" only consults the routing table to pick a
    # local address; no packet need reach the peer. Use RFC 5737 TEST-NET so we do not
    # imply reliance on a public resolver or send traffic off-host.
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
    port = int(env_port) if env_port else resolved_proxy_port
    return {"serverIP": server_ip, "port": port}


def client_ui_fields_from_env() -> dict:
    """Optional WebXR client UI defaults merged into hub ``config`` and bookmarks (allowlist).

    Keys match Teleop form element ids / ``StreamConfig`` in the web client.
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
    for key, env_name in (
        ("perEyeWidth", "TELEOP_CLIENT_PER_EYE_WIDTH"),
        ("perEyeHeight", "TELEOP_CLIENT_PER_EYE_HEIGHT"),
    ):
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        try:
            out[key] = int(raw, 10)
        except ValueError:
            log.warning("%s invalid integer %r", env_name, raw)
    return out


def build_headset_bookmark_url(
    *,
    web_client_base: str,
    stream_config: dict | None = None,
    control_token: str | None = None,
) -> str:
    """Full WebXR page URL with OOB query params (``oobEnable=1``, stream fields, optional token).

    The client derives ``wss://{serverIP}:{port}/oob/v1/ws`` from ``serverIP`` + ``port`` in the query
    (same values as CloudXR signaling) when ``oobEnable=1``; it does not open OOB without that pair.
    Optional client UI keys (``codec``, ``panelHiddenAtStart``, ``perEyeWidth``, ``perEyeHeight``) are
    encoded when present on ``stream_config`` (see ``client_ui_fields_from_env``).
    """
    cfg = stream_config or {}
    if not cfg.get("serverIP") or cfg.get("port") is None:
        raise ValueError(
            "build_headset_bookmark_url requires stream_config with serverIP and port (OOB WS is derived from them)"
        )
    params: dict[str, str] = {"oobEnable": "1"}
    if control_token:
        params["controlToken"] = control_token
    for key in ("serverIP", "proxyUrl", "mediaAddress"):
        v = cfg.get(key)
        if v is not None and v != "":
            params[key] = str(v)
    for key in ("port", "mediaPort"):
        v = cfg.get(key)
        if v is not None:
            params[key] = str(int(v))
    v = cfg.get("codec")
    if v is not None and str(v).strip() != "":
        params["codec"] = str(v).strip()
    v = cfg.get("panelHiddenAtStart")
    if isinstance(v, bool):
        params["panelHiddenAtStart"] = "true" if v else "false"
    elif v is not None and str(v).strip() != "":
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "on"):
            params["panelHiddenAtStart"] = "true"
        elif s in ("0", "false", "no", "off"):
            params["panelHiddenAtStart"] = "false"
    for key in ("perEyeWidth", "perEyeHeight"):
        v = cfg.get(key)
        if v is not None:
            try:
                params[key] = str(int(v))
            except (TypeError, ValueError):
                pass
    q = urlencode(params)
    base = web_client_base.rstrip("/")
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{q}"


def resolve_lan_host_for_oob() -> str:
    """PC LAN address the headset uses for ``https://…:8080/`` and ``wss://…:PROXY_PORT`` (wireless OOB)."""
    h = os.environ.get("TELEOP_PROXY_HOST", "").strip() or guess_lan_ipv4()
    if not h:
        raise RuntimeError(
            "Wireless --setup-oob HOST:PORT needs this PC's LAN IP for WebXR/WSS URLs. "
            "Set TELEOP_PROXY_HOST to an address the headset can reach (or fix routing so guess_lan_ipv4() works)."
        )
    return h


def print_oob_hub_startup_banner(*, oob_mode: str, lan_host: str | None = None) -> None:
    """Printed instructions for OOB + adb (``oob_mode``: ``tethered`` | ``wireless``).

    Wording follows ``docs/source/references/oob_teleop_control.rst`` (section *End-to-end workflow*).
    """
    port = wss_proxy_port()
    token = os.environ.get("CONTROL_TOKEN") or None
    is_tethered = oob_mode == "tethered"

    if is_tethered:
        primary_host = "127.0.0.1"
    else:
        if not lan_host:
            lan_host = resolve_lan_host_for_oob()
        primary_host = lan_host

    web_base = TETHERED_LOCAL_WEB_CLIENT if is_tethered else DEFAULT_WEB_CLIENT_ORIGIN
    stream_cfg = default_initial_stream_config(port)
    stream_cfg = {**stream_cfg, "serverIP": primary_host}

    web_client_base_override = web_client_base_override_from_env()
    if web_client_base_override:
        web_base = web_client_base_override

    stream_cfg = {**stream_cfg, **client_ui_fields_from_env()}

    primary_base = f"https://{primary_host}:{port}"
    bookmark_primary = build_headset_bookmark_url(
        web_client_base=web_base,
        stream_config=stream_cfg,
        control_token=token,
    )
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
    if oob_mode == "tethered":
        print(
            "  adb: USB tethered — one device in `adb devices`; tool sets up adb reverse + UDP relay, then opens the page."
        )
    else:
        print(
            "  adb: wireless — `adb connect` to your device; this PC must be reachable at the "
            "LAN addresses below."
        )
    print()
    print("  Step 1 — Headset: Teleop page URL (doc: start with hub + adb automation)")
    print(
        '           After this process logs "WSS proxy listening on port …", `--setup-oob` runs '
        "`adb` to open the page on the headset. If that fails, open this URL on the headset yourself:"
    )
    print(f"           {bookmark_primary}")
    if web_client_base_override:
        print(
            f"           ({TELEOP_WEB_CLIENT_BASE_ENV} overrides the WebXR origin; "
            "query still targets this streaming host.)"
        )
    print(
        "           The page loads with oobEnable=1 and the same serverIP/port as CloudXR; "
        "the client connects to the hub at the wss URL above."
    )
    print()
    print("  Step 2 — This PC: Inspect from the PC (Chrome remote debugging)")
    print(f"           Open {CHROME_INSPECT_DEVICES_URL}")
    print(
        "           Under Remote Target, select the headset tab for Isaac Teleop Web Client "
        "(or the matching URL) and click inspect."
    )
    print()
    print("  Step 3 — This PC: CONNECT (required WebXR user gesture)")
    print(
        "           In that DevTools window, click CONNECT on the Teleop UI (same as tapping "
        "CONNECT on the headset)."
    )
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
