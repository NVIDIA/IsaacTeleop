#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""CloudXR WSS Proxy — terminates TLS and forwards WebSocket traffic to a CloudXR Runtime backend."""

import argparse
import asyncio
import http.client
import logging
import os
import signal
import shutil
import socket
import ssl
import subprocess
import sys
from pathlib import Path

try:
    import websockets
    from websockets.asyncio.server import serve as ws_serve
    from websockets.asyncio.client import connect as ws_connect
    from websockets.datastructures import Headers
    from websockets.http11 import Response
except ImportError:
    sys.exit("Missing dependency: websockets >= 14\nRun with:  uv run wss_proxy.py")

log = logging.getLogger("wss-proxy")

CERT_DIR = Path(__file__).resolve().parent / "certs"
CERT_FILE = CERT_DIR / "server.crt"
KEY_FILE = CERT_DIR / "server.key"
PEM_FILE = CERT_DIR / "server.pem"

# ---------------------------------------------------------------------------
# Certificate generation
# ---------------------------------------------------------------------------


def ensure_certificate() -> None:
    """Generate a self-signed certificate if one does not already exist."""
    if CERT_FILE.exists() and KEY_FILE.exists():
        if not PEM_FILE.exists():
            PEM_FILE.write_bytes(CERT_FILE.read_bytes() + KEY_FILE.read_bytes())
            PEM_FILE.chmod(0o600)
        log.info("Using existing SSL certificate from %s", CERT_FILE)
        return

    log.info("Generating self-signed SSL certificate …")
    CERT_DIR.mkdir(parents=True, exist_ok=True)
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
            str(KEY_FILE),
            "-out",
            str(CERT_FILE),
            "-days",
            "365",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
    )

    PEM_FILE.write_bytes(CERT_FILE.read_bytes() + KEY_FILE.read_bytes())
    KEY_FILE.chmod(0o600)
    PEM_FILE.chmod(0o600)
    log.info("SSL certificate generated at %s", PEM_FILE)


def build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Expose-Headers": "*",
}


def _forward_http(backend_host, backend_port, request):
    """Forward a plain HTTP GET to the backend and return its response.

    Only GET is supported — the websockets library only exposes GET requests
    (HTTP/1.1 upgrade path), and CORS preflight is handled separately.
    """
    conn = http.client.HTTPConnection(backend_host, backend_port, timeout=5)
    try:
        conn.request("GET", request.path or "/")
        resp = conn.getresponse()
        body = resp.read()
        headers = Headers(
            {k: v for k, v in resp.getheaders() if k.lower() != "transfer-encoding"}
        )
        headers.update(CORS_HEADERS)
        return Response(resp.status, resp.reason, headers, body)
    except socket.timeout:
        return Response(
            504,
            "Gateway Timeout",
            Headers({"Content-Type": "text/plain", **CORS_HEADERS}),
            b"Backend did not respond in time.\n",
        )
    except (http.client.HTTPException, OSError) as exc:
        log.warning("Backend HTTP request failed: %s", exc)
        return Response(
            502,
            "Bad Gateway",
            Headers({"Content-Type": "text/plain", **CORS_HEADERS}),
            f"Backend connection failed: {exc}\n".encode(),
        )
    finally:
        conn.close()


def _make_http_handler(backend_host, backend_port):
    """Create a process_request callback that forwards non-WebSocket requests."""

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
        return await asyncio.to_thread(
            _forward_http, backend_host, backend_port, request
        )

    return handle_http_request


def add_cors_headers(connection, request, response):
    """Attach CORS headers to every WebSocket handshake response."""
    response.headers.update(CORS_HEADERS)


# ---------------------------------------------------------------------------
# WebSocket proxy handler
# ---------------------------------------------------------------------------

# Hop-by-hop and WebSocket handshake headers that the library manages itself.
# Everything else is forwarded as-is.
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
    """Forward messages from *src* to *dst* until the connection closes."""
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

    # Forward subprotocols so the backend can negotiate them properly.
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
        log.error("Failed to connect to backend %s", backend_uri)
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _env(name: str, default: str) -> str:
    """Read from env, falling back to *default*."""
    return os.environ.get(name, default)


async def run(args: argparse.Namespace) -> None:
    ensure_certificate()
    ssl_ctx = build_ssl_context()

    def handler(ws):
        return proxy_handler(ws, args.backend_host, args.backend_port)

    http_handler = _make_http_handler(args.backend_host, args.backend_port)

    stop = asyncio.get_running_loop().create_future()

    def _stop():
        if not stop.done():
            stop.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, _stop)

    async with ws_serve(
        handler,
        host="",
        port=args.proxy_port,
        ssl=ssl_ctx,
        process_request=http_handler,
        process_response=add_cors_headers,
        compression=None,
        max_size=None,
        ping_interval=None,
        ping_timeout=None,
        close_timeout=10,
    ):
        log.info("WSS proxy listening on port %d", args.proxy_port)
        await stop
        log.info("Shutting down …")


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudXR WSS Proxy")
    parser.add_argument(
        "--backend-host",
        default=_env("BACKEND_HOST", "localhost"),
        help="CloudXR Runtime host (env: BACKEND_HOST, default: localhost)",
    )
    parser.add_argument(
        "--backend-port",
        type=int,
        default=_env("BACKEND_PORT", "49100"),
        help="CloudXR Runtime port (env: BACKEND_PORT, default: 49100)",
    )
    parser.add_argument(
        "--proxy-port",
        type=int,
        default=_env("PROXY_PORT", "48322"),
        help="Port for this WSS proxy to listen on (env: PROXY_PORT, default: 48322)",
    )
    parser.add_argument(
        "--cert-dir",
        type=Path,
        default=None,
        help="Directory containing server.crt and server.key (default: ./certs next to this script)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (shows every proxied message)",
    )
    args = parser.parse_args()

    if args.cert_dir is not None:
        global CERT_DIR, CERT_FILE, KEY_FILE, PEM_FILE
        CERT_DIR = args.cert_dir.resolve()
        CERT_FILE = CERT_DIR / "server.crt"
        KEY_FILE = CERT_DIR / "server.key"
        PEM_FILE = CERT_DIR / "server.pem"

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if not args.debug:
        logging.getLogger("websockets").setLevel(logging.WARNING)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
