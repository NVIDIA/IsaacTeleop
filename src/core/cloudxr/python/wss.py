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
    HEADSET_RELAY_REMOTE_PATH,
    OobAdbError,
    UDP_RELAY_TCP_PORT,
    adb_automation_failure_hint,
    adb_automation_from_setup_oob,
    adb_push_file,
    adb_reverse_remove_all,
    adb_start_relay,
    adb_stop_relay,
    assert_at_most_one_adb_device,
    ensure_adb_connect,
    oob_adb_automation_message,
    parse_setup_oob_cli,  # noqa: F401 — re-exported for __main__
    require_adb_on_path,
    run_adb_headset_bookmark,
    setup_adb_reverse_ports,
)
from .oob_teleop_env import (
    client_ui_fields_from_env,
    default_initial_stream_config,
    print_oob_hub_startup_banner,  # noqa: F401 — re-exported for __main__
    resolve_lan_host_for_oob,
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
    """Build ``StreamConfig`` patch from query string (flat ``serverIP=`` / ``port=`` / …)."""
    cfg: dict[str, object] = {}
    if "serverIP" in q:
        cfg["serverIP"] = q["serverIP"]
    if "proxyUrl" in q:
        cfg["proxyUrl"] = q["proxyUrl"]
    if "mediaAddress" in q:
        cfg["mediaAddress"] = q["mediaAddress"]
    if "port" in q and q["port"] != "":
        try:
            cfg["port"] = int(q["port"], 10)
        except ValueError:
            return None, "port must be an integer"
    if "mediaPort" in q and q["mediaPort"] != "":
        try:
            cfg["mediaPort"] = int(q["mediaPort"], 10)
        except ValueError:
            return None, "mediaPort must be an integer"

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
    if "perEyeWidth" in q and q["perEyeWidth"] != "":
        try:
            cfg["perEyeWidth"] = int(q["perEyeWidth"], 10)
        except ValueError:
            return None, "perEyeWidth must be an integer"
    if "perEyeHeight" in q and q["perEyeHeight"] != "":
        try:
            cfg["perEyeHeight"] = int(q["perEyeHeight"], 10)
        except ValueError:
            return None, "perEyeHeight must be an integer"

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


def _find_relay_binary() -> Path | None:
    """Locate the pre-built headset relay binary (``udprelay``) for ``adb push``.

    Search order (first existing file wins):
    1. ``TELEOP_RELAY_BINARY`` env var (explicit override)
    2. ``<package>/native/udprelay`` — CMake-copied into the build output
    3. ``<package>/../udprelay/udprelay`` — source tree when running from source
    4. ``<source_root>/src/core/cloudxr/udprelay/udprelay`` — source tree via CMakeLists parent
    """
    pkg = Path(__file__).resolve().parent
    candidates = [
        pkg / "native" / "udprelay",
        pkg.parent / "udprelay" / "udprelay",
    ]
    # When running from the CMake build output the source tree is far away;
    # walk up to find the repo root (contains src/core/cloudxr/udprelay/).
    source_root = pkg
    for _ in range(10):
        candidate = source_root / "src" / "core" / "cloudxr" / "udprelay" / "udprelay"
        if candidate.is_file():
            candidates.append(candidate)
            break
        parent = source_root.parent
        if parent == source_root:
            break
        source_root = parent

    env = os.environ.get("TELEOP_RELAY_BINARY", "").strip()
    if env:
        candidates.insert(0, Path(env))
    for p in candidates:
        if p.is_file():
            log.info("Found relay binary: %s", p)
            return p
    return None


def default_cert_paths() -> CertPaths:
    """Return cert paths under the default location (~/.cloudxr/certs)."""
    return cert_paths_from_dir(Path(get_env_config().openxr_run_dir()).parent / "certs")


async def run(
    log_file_path: str | Path | None,
    stop_future: asyncio.Future,
    backend_host: str = "localhost",
    backend_port: int = 49100,
    proxy_port: int | None = None,
    setup_oob: str | None = None,
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

    try:
        resolved_port = wss_proxy_port() if proxy_port is None else proxy_port
        adb_effective = None
        if setup_oob is not None:
            require_adb_on_path()
            adb_effective = adb_automation_from_setup_oob(setup_oob)
            if adb_effective.connect is not None:
                resolve_lan_host_for_oob()
                await asyncio.to_thread(ensure_adb_connect, adb_effective.connect)
            await asyncio.to_thread(assert_at_most_one_adb_device)
        logging.getLogger("websockets").setLevel(logging.WARNING)
        cert_paths = default_cert_paths()

        ensure_certificate(cert_paths)
        ssl_ctx = build_ssl_context(cert_paths)

        hub = None
        if setup_oob is not None:
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

        udp_relay = None
        tethered_setup_done = False

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
            try:
                if setup_oob is not None and adb_effective is not None:
                    if adb_effective.tethered:
                        from .udp_tcp_relay import UdpTcpRelay  # noqa: PLC0415

                        relay_tcp = UDP_RELAY_TCP_PORT
                        udp_relay = UdpTcpRelay(tcp_port=relay_tcp)
                        await udp_relay.start()

                        await asyncio.to_thread(
                            setup_adb_reverse_ports,
                            resolved_port,
                            relay_tcp,
                            8080,
                        )
                        tethered_setup_done = True

                        relay_bin = _find_relay_binary()
                        if relay_bin:
                            await asyncio.to_thread(
                                adb_push_file,
                                relay_bin,
                                HEADSET_RELAY_REMOTE_PATH,
                            )
                            await asyncio.to_thread(
                                adb_start_relay,
                                HEADSET_RELAY_REMOTE_PATH,
                                47998,
                                relay_tcp,
                            )
                        else:
                            log.warning(
                                "Headset relay binary not found; push it manually to %s "
                                "and start with: udprelay -udp-port 47998 -tcp-port %d",
                                HEADSET_RELAY_REMOTE_PATH,
                                relay_tcp,
                            )

                    rc, adb_diag = await asyncio.to_thread(
                        run_adb_headset_bookmark,
                        resolved_port=resolved_port,
                        adb=adb_effective,
                    )
                    if rc != 0:
                        hint = adb_automation_failure_hint(adb_diag)
                        detail = adb_diag if adb_diag else ""
                        raise OobAdbError(oob_adb_automation_message(rc, detail, hint))
                await stop_future
                log.info("Shutting down ...")
            finally:
                if tethered_setup_done:
                    await asyncio.to_thread(adb_stop_relay, HEADSET_RELAY_REMOTE_PATH)
                    await asyncio.to_thread(adb_reverse_remove_all)
                if udp_relay is not None:
                    await udp_relay.stop()
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
