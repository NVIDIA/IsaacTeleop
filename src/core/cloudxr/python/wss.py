#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""CloudXR WSS Proxy — terminates TLS and forwards WebSocket traffic to a CloudXR Runtime backend."""

import asyncio
import errno
import http.client
import logging
import shutil
import ssl
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .env_config import get_env_config

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


def _forward_http(backend_host, backend_port, request):
    """Forward plain HTTP requests to the backend and return its response."""
    conn = http.client.HTTPConnection(backend_host, backend_port, timeout=5)
    try:
        method = getattr(request, "method", "GET")
        body = getattr(request, "body", None)

        hop_by_hop_headers = {
            "host",
            "connection",
            "upgrade",
            "proxy-connection",
            "transfer-encoding",
            "content-length",
            "keep-alive",
            "te",
            "trailer",
        }
        request_headers = {}
        for k, v in request.headers.raw_items():
            if k.lower() not in hop_by_hop_headers:
                request_headers[k] = v

        conn.request(method, request.path or "/", body=body, headers=request_headers)
        resp = conn.getresponse()
        body = resp.read()
        headers = Headers(
            (k, v) for k, v in resp.getheaders() if k.lower() != "transfer-encoding"
        )
        headers.update(CORS_HEADERS)
        return Response(resp.status, resp.reason, headers, body)
    except TimeoutError:
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
    log_file_path: str | Path,
    stop_future: asyncio.Future,
    backend_host: str = "localhost",
    backend_port: int = 49100,
    proxy_port: int = 48322,
) -> None:
    logger = log
    logger.setLevel(logging.INFO)
    logger.propagate = False
    file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)

    try:
        logging.getLogger("websockets").setLevel(logging.WARNING)
        cert_paths = default_cert_paths()

        ensure_certificate(cert_paths)
        ssl_ctx = build_ssl_context(cert_paths)

        def handler(ws):
            return proxy_handler(ws, backend_host, backend_port)

        http_handler = _make_http_handler(backend_host, backend_port)

        async with ws_serve(
            handler,
            host="",
            port=proxy_port,
            ssl=ssl_ctx,
            process_request=http_handler,
            process_response=add_cors_headers,
            compression=None,
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            close_timeout=10,
        ):
            log.info("WSS proxy listening on port %d", proxy_port)
            await stop_future
            log.info("Shutting down ...")
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            raise RuntimeError(
                f"WSS proxy port {proxy_port} is already in use. "
                f"Set PROXY_PORT to a different port or stop the process using {proxy_port}."
            ) from e
        raise
    finally:
        logger.removeHandler(file_handler)
        file_handler.close()
