#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""CloudXR WSS Proxy — terminates TLS and forwards WebSocket traffic to a CloudXR Runtime backend."""

import asyncio
import errno
import json
import logging
import mimetypes
import os
import socket
from urllib.parse import unquote, urlparse
import shutil
import ssl
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .env_config import get_env_config

_STATIC_OPERATOR_DIR = Path(__file__).parent / "static" / "operator"

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

WSS_PROXY_DEFAULT_PORT = 48322


def wss_proxy_port() -> int:
    """TCP port for the WSS proxy (``PROXY_PORT`` environment variable if set, else ``48322``)."""
    raw = os.environ.get("PROXY_PORT", "").strip()
    if raw:
        return int(raw)
    return WSS_PROXY_DEFAULT_PORT


def _guess_lan_ipv4() -> str | None:
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


def operator_dashboard_urls(port: int | None = None) -> list[str]:
    """HTTPS URLs for the operator UI: localhost, plus a guessed LAN address when available."""
    p = wss_proxy_port() if port is None else port
    urls = [f"https://127.0.0.1:{p}/teleop/"]
    lan = _guess_lan_ipv4()
    if lan:
        urls.append(f"https://{lan}:{p}/teleop/")
    return urls


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


def _is_teleop_hub_http_path(path: str) -> bool:
    """True for HTTP paths owned by the teleop hub (operator UI, WS mount, state API)."""
    if path.rstrip("/") == "/teleop":
        return True
    if path.startswith("/teleop/"):
        return True
    if path == "/api/teleop/v1/state":
        return True
    return False


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

        if hub is not None:
            # Operator static UI
            if path.rstrip("/") == "/teleop":
                try:
                    body = (_STATIC_OPERATOR_DIR / "index.html").read_bytes()
                except OSError:
                    return Response(
                        404,
                        "Not Found",
                        Headers({"Content-Type": "text/plain", **CORS_HEADERS}),
                        b"Operator UI not installed",
                    )
                return Response(
                    200,
                    "OK",
                    Headers(
                        {"Content-Type": "text/html; charset=utf-8", **CORS_HEADERS}
                    ),
                    body,
                )
            if path.startswith("/teleop/") and not path.startswith("/teleop/v1/"):
                filename = path.removeprefix("/teleop/")
                if not filename:
                    try:
                        body = (_STATIC_OPERATOR_DIR / "index.html").read_bytes()
                    except OSError:
                        return Response(
                            404,
                            "Not Found",
                            Headers({"Content-Type": "text/plain", **CORS_HEADERS}),
                            b"Operator UI not installed",
                        )
                    return Response(
                        200,
                        "OK",
                        Headers(
                            {"Content-Type": "text/html; charset=utf-8", **CORS_HEADERS}
                        ),
                        body,
                    )
                static_path = _STATIC_OPERATOR_DIR / filename
                if static_path.is_file() and static_path.resolve().is_relative_to(
                    _STATIC_OPERATOR_DIR.resolve()
                ):
                    try:
                        file_body = static_path.read_bytes()
                    except OSError:
                        return Response(
                            404,
                            "Not Found",
                            Headers({"Content-Type": "text/plain", **CORS_HEADERS}),
                            b"Not found",
                        )
                    ct, _ = mimetypes.guess_type(filename)
                    ct = ct or "application/octet-stream"
                    return Response(
                        200,
                        "OK",
                        Headers({"Content-Type": ct, **CORS_HEADERS}),
                        file_body,
                    )
                return Response(
                    404,
                    "Not Found",
                    Headers({"Content-Type": "text/plain", **CORS_HEADERS}),
                    b"Not found",
                )

            # Hub state API
            if path == "/api/teleop/v1/state":
                token = request.headers.get("X-Control-Token") or _query_param(
                    request.path, "token"
                )
                if not hub.check_token(token):
                    return Response(
                        401,
                        "Unauthorized",
                        Headers({"Content-Type": "application/json", **CORS_HEADERS}),
                        json.dumps({"error": "Unauthorized"}).encode(),
                    )
                snapshot = await hub.get_snapshot()
                return Response(
                    200,
                    "OK",
                    Headers({"Content-Type": "application/json", **CORS_HEADERS}),
                    json.dumps(snapshot).encode(),
                )

        if hub is None and _is_teleop_hub_http_path(path):
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


def _query_param(raw_path: str, name: str) -> str | None:
    """Extract a single query parameter value from a raw request path (URL-decoded)."""
    if "?" not in raw_path:
        return None
    qs = raw_path.split("?", 1)[1]
    for part in qs.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            if unquote(k) == name:
                return unquote(v, errors="replace")
    return None


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
    enable_hub: bool = False,
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
        logging.getLogger("websockets").setLevel(logging.WARNING)
        cert_paths = default_cert_paths()

        ensure_certificate(cert_paths)
        ssl_ctx = build_ssl_context(cert_paths)

        hub = None
        if enable_hub:
            from .teleop_ws_hub import TeleopControlHub  # noqa: PLC0415

            control_token = os.environ.get("CONTROL_TOKEN") or None
            hub = TeleopControlHub(control_token=control_token)
            log.info(
                "Teleop control hub enabled (token=%s)",
                "set" if control_token else "none",
            )

        def handler(ws):
            if hub is not None:
                path = _normalize_request_path(ws.request.path or "/")
                if path == "/teleop/v1/ws":
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
            await stop_future
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
