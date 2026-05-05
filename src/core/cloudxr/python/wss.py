#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""CloudXR WSS Proxy — terminates TLS and forwards WebSocket traffic to a CloudXR Runtime backend."""

import asyncio
import errno
import json
import logging
import os
from urllib.parse import unquote, urlparse
import shutil
import ssl
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .env_config import get_env_config
from .oob_teleop_adb import (
    OobAdbError,
    run_oob_connect,
)
from .oob_teleop_env import (
    client_ui_fields_from_env,
    default_initial_stream_config,
    oob_progress,
    wss_proxy_port,
)
from .oob_teleop_hub import OOB_WS_PATH

try:
    import websockets
    from websockets.asyncio.client import connect as ws_connect
    from websockets.asyncio.server import serve as ws_serve
    from websockets.datastructures import Headers
    from websockets.http11 import Response
except ImportError:
    sys.exit(
        "Missing dependency: websockets >= 14\n"
        "Install with: uv pip install --find-links=install/wheels 'isaacteleop[cloudxr]'"
    )


def _patch_request_parser_for_cors():
    """Allow HTTP OPTIONS through the websockets request parser.

    ``websockets >= 14`` rejects non-GET methods in ``Request.parse`` before
    ``process_request`` fires.  This wraps the parser so that OPTIONS requests
    (CORS preflight) are surfaced as a normal ``Request`` — the existing
    ``process_request`` hook in ``_make_http_handler`` already returns the
    correct 200 + CORS-headers response for them.
    """
    from websockets.http11 import Request, parse_headers

    _orig_parse = Request.parse.__func__

    @classmethod
    def _cors_aware_parse(cls, read_line):
        try:
            return (yield from _orig_parse(cls, read_line))
        except ValueError as exc:
            if "got OPTIONS" not in str(exc):
                raise
            headers = yield from parse_headers(read_line)
            return cls("/__cors_preflight__", headers)

    Request.parse = _cors_aware_parse


_patch_request_parser_for_cors()

log = logging.getLogger("wss-proxy")


@dataclass(frozen=True)
class CertPaths:
    cert_dir: Path
    cert_file: Path
    key_file: Path


def cert_paths_from_dir(cert_dir: Path) -> CertPaths:
    cert_dir = cert_dir.resolve()
    return CertPaths(
        cert_dir=cert_dir,
        cert_file=cert_dir / "server.crt",
        key_file=cert_dir / "server.key",
    )


def ensure_certificate(cert_paths: CertPaths) -> None:
    """Generate a self-signed certificate if one does not already exist."""
    cert_exists = cert_paths.cert_file.exists()
    key_exists = cert_paths.key_file.exists()
    if cert_exists != key_exists:
        missing_file = cert_paths.key_file if cert_exists else cert_paths.cert_file
        raise RuntimeError(
            f"Found partial TLS cert pair in {cert_paths.cert_dir}; missing {missing_file.name}. "
            "Restore both files or remove both and retry."
        )

    if cert_exists and key_exists:
        log.info("Using existing SSL certificate from %s", cert_paths.cert_file)
        return

    log.info("Generating self-signed SSL certificate ...")
    cert_paths.cert_dir.mkdir(parents=True, exist_ok=True)
    openssl_bin = shutil.which("openssl")
    if not openssl_bin:
        raise RuntimeError(
            "OpenSSL executable not found on PATH; cannot generate TLS certificates."
        )

    subprocess.run(
        [
            openssl_bin,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(cert_paths.key_file),
            "-out",
            str(cert_paths.cert_file),
            "-days",
            "365",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )

    cert_paths.key_file.chmod(0o600)
    log.info("SSL certificate generated at %s", cert_paths.cert_file)


def build_ssl_context(cert_paths: CertPaths) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(
        certfile=str(cert_paths.cert_file), keyfile=str(cert_paths.key_file)
    )
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Expose-Headers": "*",
}


def _cert_html() -> bytes:
    return (
        b"<!doctype html><html><head><meta charset=utf-8>"
        b"<style>body{font-family:system-ui,sans-serif;display:flex;"
        b"align-items:center;justify-content:center;height:100vh;margin:0;"
        b"background:#f5f5f5;color:#222}div{text-align:center}"
        b"h1{font-weight:600;font-size:1.5rem;margin-bottom:.5rem}"
        b"p{color:#555;font-size:1rem}</style></head>"
        b"<body><div><h1>Certificate Accepted</h1>"
        b"<p>You can close this tab and return to the web client.</p>"
        b"</div></body></html>"
    )


def _normalize_request_path(raw_path: str) -> str:
    """Normalize HTTP request-target: query stripped, absolute-URL form, ``%``-decoding, ``//``, ``.`` / ``..``."""
    path = (raw_path or "/").split("?")[0] or "/"
    if path.startswith(("http://", "https://")):
        path = urlparse(path).path or "/"
    path = unquote(path, errors="replace")
    segments = [p for p in path.split("/") if p and p != "."]
    stack: list[str] = []
    for seg in segments:
        if seg == "..":
            if stack:
                stack.pop()
        else:
            stack.append(seg)
    if not stack:
        return "/"
    return "/" + "/".join(stack)


def _is_oob_hub_http_path(path: str) -> bool:
    """True for OOB HTTP API paths on the WSS proxy."""
    return path in (
        "/api/oob/v1/state",
        "/api/oob/v1/config",
    )


def _parse_query_params(raw_path: str) -> dict[str, str]:
    """First occurrence wins; keys and values are URL-decoded."""
    if "?" not in raw_path:
        return {}
    qs = raw_path.split("?", 1)[1]
    out: dict[str, str] = {}
    for part in qs.split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            k = unquote(k)
            if k not in out:
                out[k] = unquote(v, errors="replace")
        else:
            k = unquote(part)
            if k not in out:
                out[k] = ""
    return out


def _stream_config_from_query(q: dict[str, str]) -> tuple[dict | None, str | None]:
    """Build ``StreamConfig`` patch from query string (``serverIP=`` / ``port=`` / …)."""
    cfg: dict[str, object] = {}
    if "serverIP" in q:
        cfg["serverIP"] = q["serverIP"]
    if "port" in q and q["port"] != "":
        try:
            cfg["port"] = int(q["port"], 10)
        except ValueError:
            return None, "port must be an integer"
    if "panelHiddenAtStart" in q and q["panelHiddenAtStart"] != "":
        s = q["panelHiddenAtStart"].strip().lower()
        if s in ("1", "true", "yes", "on"):
            cfg["panelHiddenAtStart"] = True
        elif s in ("0", "false", "no", "off"):
            cfg["panelHiddenAtStart"] = False
        else:
            return None, "panelHiddenAtStart must be true or false"
    if "codec" in q and q["codec"] != "":
        cfg["codec"] = q["codec"]
    return cfg, None


def _oob_token(request, q: dict[str, str]) -> str | None:
    h = request.headers.get("X-Control-Token")
    if h:
        return h
    t = q.get("token")
    return t if t else None


def _json_response(status: int, phrase: str, body: dict) -> Response:
    return Response(
        status,
        phrase,
        Headers({"Content-Type": "application/json", **CORS_HEADERS}),
        json.dumps(body).encode(),
    )


def _make_http_handler(backend_host, backend_port, hub=None):
    async def handle_http_request(connection, request):
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None

        if request.headers.get("Access-Control-Request-Method"):
            return Response(
                200,
                "OK",
                Headers({"Content-Type": "text/plain", **CORS_HEADERS}),
                b"OK",
            )

        path = _normalize_request_path(request.path or "/")
        raw_path = request.path or "/"
        q = _parse_query_params(raw_path)

        if hub is not None and _is_oob_hub_http_path(path):
            token = _oob_token(request, q)
            if path == "/api/oob/v1/state":
                if not hub.check_token(token):
                    return _json_response(
                        401, "Unauthorized", {"error": "Unauthorized"}
                    )
                snapshot = await hub.get_snapshot()
                return Response(
                    200,
                    "OK",
                    Headers({"Content-Type": "application/json", **CORS_HEADERS}),
                    json.dumps(snapshot).encode(),
                )

            if path == "/api/oob/v1/config":
                if not hub.check_token(token):
                    return _json_response(
                        401, "Unauthorized", {"error": "Unauthorized"}
                    )
                cfg, err = _stream_config_from_query(q)
                if err:
                    return _json_response(400, "Bad Request", {"error": err})
                payload = {
                    "config": cfg,
                    "targetClientId": q.get("targetClientId"),
                    "token": token,
                }
                status, body = await hub.http_oob_set_config(payload)
                phrase = {
                    200: "OK",
                    400: "Bad Request",
                    401: "Unauthorized",
                    404: "Not Found",
                }.get(status, "Error")
                return _json_response(status, phrase, body)

        if hub is None and _is_oob_hub_http_path(path):
            return Response(
                404,
                "Not Found",
                Headers({"Content-Type": "text/plain", **CORS_HEADERS}),
                b"Not found",
            )

        return Response(
            200,
            "OK",
            Headers({"Content-Type": "text/html; charset=utf-8", **CORS_HEADERS}),
            _cert_html(),
        )

    return handle_http_request


def add_cors_headers(connection, request, response):
    response.headers.update(CORS_HEADERS)


_SKIP_HEADERS = {
    "host",
    "upgrade",
    "connection",
    "sec-websocket-key",
    "sec-websocket-version",
    "sec-websocket-accept",
    "sec-websocket-extensions",
    "sec-websocket-protocol",
}


def _is_backend_connection_refused(exc: BaseException) -> bool:
    """True when ``ws_connect`` failed because nothing is listening (runtime not running)."""
    if isinstance(exc, ConnectionRefusedError):
        return True
    if isinstance(exc, OSError) and exc.errno in (
        errno.ECONNREFUSED,
        getattr(errno, "WSAECONNREFUSED", -1),
    ):
        return True
    if isinstance(exc, OSError):
        msg = str(exc).lower()
        if "errno 61" in msg or "errno 111" in msg:
            return True
        if "connection refused" in msg:
            return True
    return False


async def _pipe(src, dst, label: str):
    try:
        async for msg in src:
            if isinstance(msg, str):
                log.debug("%s text (%d chars): %s", label, len(msg), msg[:200])
            else:
                log.debug("%s binary (%d bytes)", label, len(msg))
            await dst.send(msg)
    except websockets.ConnectionClosed as exc:
        rcvd = exc.rcvd
        log.debug(
            "%s closed: code=%s reason=%s",
            label,
            rcvd.code if rcvd else None,
            rcvd.reason if rcvd else "",
        )
        try:
            if exc.rcvd:
                await dst.close(exc.rcvd.code, exc.rcvd.reason)
            else:
                await dst.close()
        except websockets.ConnectionClosed:
            pass


async def proxy_handler(client, backend_host: str, backend_port: int):
    path = client.request.path or "/"
    backend_uri = f"ws://{backend_host}:{backend_port}{path}"

    headers_to_forward = {
        k: v
        for k, v in client.request.headers.raw_items()
        if k.lower() not in _SKIP_HEADERS
    }

    subprotocols = client.request.headers.get_all("Sec-WebSocket-Protocol")

    try:
        backend = await ws_connect(
            backend_uri,
            additional_headers=headers_to_forward,
            subprotocols=subprotocols or None,
            compression=None,
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            close_timeout=10,
        )
    except OSError as exc:
        if _is_backend_connection_refused(exc):
            log.warning(
                "No CloudXR runtime at ws://%s:%s (connection refused) for path %s — "
                "expected when running WSS+hub without the runtime; teleop signaling uses %s.",
                backend_host,
                backend_port,
                path,
                OOB_WS_PATH,
            )
            return
        log.exception("Failed to connect to backend %s", backend_uri)
        return
    except Exception:
        log.exception("Failed to connect to backend %s", backend_uri)
        return

    log.info("Proxying %s -> %s", client.remote_address, backend_uri)

    try:
        client_to_backend = asyncio.create_task(
            _pipe(client, backend, f"client->backend [{path}]")
        )
        backend_to_client = asyncio.create_task(
            _pipe(backend, client, f"backend->client [{path}]")
        )

        _done, pending = await asyncio.wait(
            [client_to_backend, backend_to_client],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    except Exception:
        log.exception("Proxy error on %s", path)
    finally:
        await backend.close()
        log.info("Connection closed: %s", path)


def default_cert_paths() -> CertPaths:
    """Return cert paths under the default location (~/.cloudxr/certs)."""
    return cert_paths_from_dir(Path(get_env_config().openxr_run_dir()).parent / "certs")


async def run(
    log_file_path: str | Path | None,
    stop_future: asyncio.Future,
    backend_host: str = "localhost",
    backend_port: int = 49100,
    proxy_port: int | None = None,
    setup_oob: bool = False,
    usb_local: bool = False,
) -> None:
    logger = log
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if log_file_path is not None:
        _handler: logging.Handler = logging.FileHandler(
            log_file_path, mode="a", encoding="utf-8"
        )
    else:
        _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(_log_fmt)
    logger.addHandler(_handler)
    # Route oob-teleop-adb and oob-teleop-env logs to the same destination
    for _extra_log_name in ("oob-teleop-adb", "oob-teleop-env"):
        _extra_log = logging.getLogger(_extra_log_name)
        _extra_log.setLevel(logging.INFO)
        _extra_log.propagate = False
        _extra_log.addHandler(_handler)

    try:
        resolved_port = wss_proxy_port() if proxy_port is None else proxy_port

        logging.getLogger("websockets").setLevel(logging.WARNING)
        cert_paths = default_cert_paths()

        ensure_certificate(cert_paths)
        ssl_ctx = build_ssl_context(cert_paths)

        hub = None
        if setup_oob:
            from .oob_teleop_hub import OOBControlHub  # noqa: PLC0415

            control_token = os.environ.get("CONTROL_TOKEN") or None
            initial = {
                **default_initial_stream_config(resolved_port),
                **client_ui_fields_from_env(),
            }
            hub = OOBControlHub(control_token=control_token, initial_config=initial)
            log.info(
                "Teleop control hub enabled (token=%s) OOB_WS=%s initial_stream=%s",
                "set" if control_token else "none",
                OOB_WS_PATH,
                initial,
            )

        def handler(ws):
            if hub is not None:
                path = _normalize_request_path(ws.request.path or "/")
                if path == OOB_WS_PATH:
                    return hub.handle_connection(ws)
            return proxy_handler(ws, backend_host, backend_port)

        http_handler = _make_http_handler(backend_host, backend_port, hub=hub)

        async with ws_serve(
            handler,
            host="",
            port=resolved_port,
            ssl=ssl_ctx,
            process_request=http_handler,
            process_response=add_cors_headers,
            compression=None,
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            close_timeout=10,
        ):
            log.info("WSS proxy listening on port %d", resolved_port)

            # ------------------------------------------------------------------
            # USB-local: HTTPS static client (:func:`oob_teleop_env.usb_ui_port`,
            # default 8080; override via ``USB_UI_PORT`` env) + adb reverse
            # (WSS / backend / TURN) + coturn. Assets are ensured in
            # require_usb_local_webxr_static_dir (also called from launcher).
            # ------------------------------------------------------------------
            # The coturn handle lives in a 1-element list so the watchdog
            # (H7) can replace it after a mid-session restart while keeping
            # cleanup pointing at whatever's currently live.
            _usb_coturn_proc_box: list = [None]
            _usb_coturn_watch_task: asyncio.Task | None = None
            _usb_https_thread = None
            _usb_https_httpd = None
            _usb_turn_port_resolved: int | None = None

            if usb_local:
                from .oob_teleop_env import (  # noqa: PLC0415
                    USB_TURN_USER,
                    USB_TURN_CREDENTIAL,
                    require_usb_local_webxr_static_dir,
                    start_usb_local_https_server,
                    stop_usb_local_https_server,
                    usb_backend_port,
                    usb_turn_port,
                    usb_ui_port,
                )

                # Resolve once so the coturn bind, adb reverse, and shutdown
                # paths all agree (env vars are read at process start; pinning
                # to a local also avoids re-reading on the cleanup path after
                # the env may have been mutated).
                _usb_turn_port_resolved = usb_turn_port()
                from .oob_teleop_adb import (  # noqa: PLC0415
                    setup_adb_reverse_ports,
                    teardown_adb_reverse_ports,
                    setup_adb_reverse_turn,
                    teardown_adb_reverse_turn,
                    start_coturn,
                    stop_coturn,
                    verify_adb_reverse_rules,
                    verify_coturn_listening,
                    watch_coturn,
                )

                oob_progress(
                    "usb-local",
                    f"serving WebXR static client over HTTPS on https://localhost:{usb_ui_port()} ...",
                )
                static_root = require_usb_local_webxr_static_dir()
                _usb_https_thread, _usb_https_httpd = start_usb_local_https_server(
                    static_root,
                    cert_file=cert_paths.cert_file,
                    key_file=cert_paths.key_file,
                    port=usb_ui_port(),
                )

                # 2. adb reverse for TCP ports (WebXR UI, WSS proxy, backend)
                _expected_tcp_ports = [
                    usb_ui_port(),
                    wss_proxy_port(),
                    usb_backend_port(),
                ]
                oob_progress(
                    "usb-local",
                    f"adb reverse: forwarding TCP ports {_expected_tcp_ports} "
                    "from headset loopback to this PC ...",
                )
                try:
                    setup_adb_reverse_ports()
                    log.info("USB-local: adb reverse TCP ports active")
                except (OobAdbError, subprocess.CalledProcessError) as exc:
                    log.warning("USB-local: adb reverse TCP setup failed: %s", exc)
                    print(
                        f"\n\033[33mUSB-local: adb reverse failed.\n{exc}\033[0m\n",
                        file=sys.stderr,
                    )
                # Validate: rule actually present in `adb reverse --list`.
                missing = verify_adb_reverse_rules(_expected_tcp_ports)
                if missing:
                    log.warning(
                        "USB-local: adb reverse rules missing for ports %s after setup",
                        missing,
                    )
                    print(
                        f"\n\033[33mUSB-local: adb reverse rules NOT present for "
                        f"ports {missing} (the headset will not reach them). "
                        f"Try `adb reverse --list` and re-plug the USB cable.\033[0m\n",
                        file=sys.stderr,
                    )
                else:
                    oob_progress(
                        "usb-local",
                        f"verified: adb reverse rules present for {_expected_tcp_ports}",
                    )

                # 3. coturn TURN server (ICE relay required for WebRTC)
                oob_progress(
                    "usb-local",
                    f"starting coturn TURN server on 127.0.0.1:{_usb_turn_port_resolved} "
                    "(WebRTC ICE relay) ...",
                )
                _usb_coturn_proc_box[0] = start_coturn(
                    _usb_turn_port_resolved, USB_TURN_USER, USB_TURN_CREDENTIAL
                )
                if _usb_coturn_proc_box[0] is None:
                    print(
                        "\n\033[33mUSB-local: coturn not running — WebRTC will "
                        "fail. Install with: sudo apt install coturn\033[0m\n",
                        file=sys.stderr,
                    )
                else:
                    # Validate: TCP-connect from the same loopback the headset
                    # uses (via adb reverse). Catches "process up but listener
                    # not bound yet / config error" before signalling proceeds.
                    if verify_coturn_listening(_usb_turn_port_resolved):
                        oob_progress(
                            "usb-local",
                            f"verified: coturn accepting TCP on 127.0.0.1:{_usb_turn_port_resolved}",
                        )
                    else:
                        log.warning(
                            "USB-local: coturn process is up but not accepting "
                            "TCP on 127.0.0.1:%d",
                            _usb_turn_port_resolved,
                        )
                        print(
                            f"\n\033[33mUSB-local: coturn pid {_usb_coturn_proc_box[0].pid} "
                            f"is alive but NOT listening on 127.0.0.1:{_usb_turn_port_resolved} — "
                            f"WebRTC will fail to allocate relay candidates. "
                            f"Tail /tmp/coturn-cloudxr-{_usb_turn_port_resolved}.log "
                            f"for the cause.\033[0m\n",
                            file=sys.stderr,
                        )
                    _usb_coturn_watch_task = asyncio.create_task(
                        watch_coturn(
                            _usb_coturn_proc_box,
                            turn_port=_usb_turn_port_resolved,
                            user=USB_TURN_USER,
                            credential=USB_TURN_CREDENTIAL,
                        ),
                        name="cloudxr-coturn-watchdog",
                    )

                # 4. adb reverse for TURN port (headset → PC coturn)
                oob_progress(
                    "usb-local",
                    f"adb reverse: forwarding TURN port {_usb_turn_port_resolved} "
                    "(headset → PC coturn) ...",
                )
                try:
                    setup_adb_reverse_turn(_usb_turn_port_resolved)
                    log.info(
                        "USB-local: adb reverse TURN active (port %d)",
                        _usb_turn_port_resolved,
                    )
                except (OobAdbError, subprocess.CalledProcessError) as exc:
                    log.warning("USB-local: adb reverse TURN setup failed: %s", exc)
                    print(
                        f"\n\033[33mUSB-local: adb reverse TURN failed.\n{exc}\033[0m\n",
                        file=sys.stderr,
                    )
                # Validate: TURN reverse rule is present.
                missing_turn = verify_adb_reverse_rules([_usb_turn_port_resolved])
                if missing_turn:
                    log.warning(
                        "USB-local: TURN adb reverse rule missing after setup (port %d)",
                        _usb_turn_port_resolved,
                    )
                    print(
                        f"\n\033[33mUSB-local: adb reverse TURN rule NOT present "
                        f"for port {_usb_turn_port_resolved} — the headset cannot "
                        f"reach coturn. Re-plug the USB cable.\033[0m\n",
                        file=sys.stderr,
                    )
                else:
                    oob_progress(
                        "usb-local",
                        f"verified: adb reverse TURN rule present for port "
                        f"{_usb_turn_port_resolved}",
                    )

                oob_progress(
                    "usb-local",
                    "USB-local subsystem startup done "
                    "(HTTPS UI + adb reverse + coturn — see warnings above for any partial failures)",
                )

            oob_monitor_task: asyncio.Task | None = None
            wifi_monitor_task: asyncio.Task | None = None
            if setup_oob:
                from .oob_teleop_adb import (  # noqa: PLC0415
                    build_teleop_url,
                    monitor_headset_wifi,
                )

                wifi_monitor_task = asyncio.create_task(
                    monitor_headset_wifi(), name="cloudxr-headset-wifi-monitor"
                )
                log.info("Starting OOB ADB+CDP automation")
                oob_progress(
                    "setup-oob",
                    "opening teleop page on headset via adb + auto-clicking "
                    "CONNECT via Chrome DevTools Protocol ...",
                )
                try:
                    oob_monitor_task = await run_oob_connect(
                        resolved_port=resolved_port, usb_local=usb_local
                    )
                    log.info("OOB automation completed — CONNECT clicked")
                    oob_progress(
                        "setup-oob",
                        "CONNECT dispatched — teleop session active "
                        "(monitoring headset error banner)",
                    )
                except Exception as err:
                    is_oob = isinstance(err, OobAdbError)
                    log.warning(
                        "OOB automation failed (non-fatal): %s",
                        err,
                        exc_info=not is_oob,
                    )
                    try:
                        fallback_url = build_teleop_url(
                            resolved_port=resolved_port, usb_local=usb_local
                        )
                    except Exception:
                        fallback_url = ""
                    msg = (
                        str(err)
                        if is_oob
                        else (
                            "OOB automation error — tap CONNECT on the headset manually."
                        )
                    )
                    suffix = (
                        f"\n  Open this URL on the headset and tap CONNECT:\n  {fallback_url}"
                        if fallback_url
                        else ""
                    )
                    print(f"\n\033[33m{msg}{suffix}\033[0m\n", file=sys.stderr)

            try:
                await stop_future
            finally:
                for task in (
                    oob_monitor_task,
                    wifi_monitor_task,
                    _usb_coturn_watch_task,
                ):
                    if task is None:
                        continue
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                if usb_local:
                    stop_coturn(_usb_coturn_proc_box[0])
                    if _usb_turn_port_resolved is not None:
                        teardown_adb_reverse_turn(_usb_turn_port_resolved)
                    teardown_adb_reverse_ports()
                    stop_usb_local_https_server(_usb_https_thread, _usb_https_httpd)
                    log.info("USB-local: cleanup complete")

            log.info("Shutting down ...")
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            raise RuntimeError(
                f"WSS proxy port {resolved_port} is already in use. "
                f"Set PROXY_PORT to a different port or stop the process using {resolved_port}."
            ) from e
        raise
    finally:
        logger.removeHandler(_handler)
        _handler.close()
