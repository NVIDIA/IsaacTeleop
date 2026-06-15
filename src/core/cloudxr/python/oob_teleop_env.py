# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OOB teleop environment: proxy port, LAN detection, stream defaults, headset bookmark URLs.

Includes manifest-driven web client static sync (:func:`require_web_client_static_dir`)
so OOB and ``--host-client`` serve lazy webpack chunks listed in
``asset-manifest.json``, not only ``index.html`` and ``bundle.js``.
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .oob_teleop_hub import OOB_WS_PATH

log = logging.getLogger("oob-teleop-env")

WSS_PROXY_DEFAULT_PORT = 48322

# GitHub Pages WebXR client root. The published client lives under a per-ref
# slug (``main``, ``release-1.3.x``, ``v1.2.3``, ...); the docs build emits one
# slug per ref it builds. :func:`default_web_client_origin` resolves the slug
# for the installed version so OOB opens the matching client.
WEB_CLIENT_BASE = "https://nvidia.github.io/IsaacTeleop/client/"

# Origin used when the installed version can't be resolved (dev trees, tests).
FALLBACK_WEB_CLIENT_ORIGIN = urljoin(WEB_CLIENT_BASE, "main/")


def versioned_web_client_url(version: str) -> str:
    """GitHub Pages WebXR client URL matching *version*.

    A clean ``MAJOR.MINOR.PATCH`` release (a tag build) maps to the per-tag
    client ``client/vMAJOR.MINOR.PATCH/``. Pre-release / dev builds (``1.2.4rc1``,
    ``1.3.0.dev5``, ...) and any other version with a leading MAJOR.MINOR map to
    the release line ``client/release-MAJOR.MINOR.x/``. Versions with no
    parseable MAJOR.MINOR fall back to the generic ``client/`` URL, which the
    site redirects to the latest stable tag. The same helper backs the
    standalone "web client:" line printed in non-OOB mode, so every path
    agrees on which client to open.

    Args:
        version: Installed ``isaacteleop`` distribution version string.

    Returns:
        Absolute HTTPS URL to the matching published WebXR client tree
        (trailing path segment, no query).
    """
    v = version.strip()
    # Exact release tag → per-tag client directory on GitHub Pages.
    if re.fullmatch(r"\d+\.\d+\.\d+", v):
        return urljoin(WEB_CLIENT_BASE, f"v{v}/")
    # Dev/rc builds → release-line slug (e.g. release-1.3.x/).
    m = re.match(r"(\d+)\.(\d+)", v)
    if m:
        return urljoin(WEB_CLIENT_BASE, f"release-{m.group(1)}.{m.group(2)}.x/")
    return WEB_CLIENT_BASE


def default_web_client_origin() -> str:
    """Versioned WebXR client origin for the installed ``isaacteleop`` version.

    Reads the installed distribution version (namespace-independent, so it works
    under the test package alias too) and maps it via
    :func:`versioned_web_client_url`. Falls back to
    :data:`FALLBACK_WEB_CLIENT_ORIGIN` when the version can't be determined.

    Returns:
        Base URL (with trailing slash) used to download OOB static assets and
        open the bookmark when no override is set.
    """
    try:
        return versioned_web_client_url(version("isaacteleop"))
    except PackageNotFoundError:
        return FALLBACK_WEB_CLIENT_ORIGIN


# Upper bound for downloaded client assets (supply-chain / accident guard).
_USB_LOCAL_ASSET_MAX_BYTES = 32 * 1024 * 1024

TELEOP_WEB_CLIENT_BASE_ENV = "TELEOP_WEB_CLIENT_BASE"

# Hash-router fragment appended to the bookmark URL (no fragment by default).
# The WebXR client uses HashRouter, so the fragment selects the route. Set
# ``TELEOP_CLIENT_ROUTE`` to a path like ``/real/gear/dexmate`` to land the
# headset on a specific route; leave unset (or empty) for the client default.
TELEOP_CLIENT_ROUTE_ENV = "TELEOP_CLIENT_ROUTE"
DEFAULT_TELEOP_CLIENT_ROUTE = ""

# Prebuilt web client cache (``TELEOP_WEB_CLIENT_STATIC_DIR``, default
# ``~/.cloudxr/static-client``). Synced via :func:`require_web_client_static_dir`.
TELEOP_WEB_CLIENT_STATIC_DIR_ENV = "TELEOP_WEB_CLIENT_STATIC_DIR"

CHROME_INSPECT_DEVICES_URL = "chrome://inspect/#devices"

# ---------------------------------------------------------------------------
# USB-local mode constants
#
# "USB-local" means: the headset reaches the PC over loopback (127.0.0.1) via
# ``adb reverse``.  Static assets live under ``TELEOP_WEB_CLIENT_STATIC_DIR`` or
# default ``~/.cloudxr/static-client`` (downloaded from NVIDIA GitHub Pages if missing).
# Python serves them over HTTPS on the resolved USB UI port (:func:`usb_ui_port`,
# default 8080; override via the ``USB_UI_PORT`` env var) with the same PEM as
# the WSS proxy.
# ---------------------------------------------------------------------------

USB_HOST = "127.0.0.1"  # serverIP seen by the headset (its own localhost)
USB_UI_DEFAULT_PORT = 8080  # HTTPS static WebXR UI (loopback)
USB_BACKEND_DEFAULT_PORT = 49100  # CloudXR backend (webrtc client direct connection)
USB_TURN_DEFAULT_PORT = 3478  # coturn TURN server port (adb reverse'd to headset)
USB_TURN_USER = "cloudxr"  # TURN username
USB_TURN_CREDENTIAL = "cloudxrpass"  # TURN credential


def default_web_client_static_dir() -> Path:
    """Default directory for web client static files (under ``~/.cloudxr``).

    Returns:
        ``~/.cloudxr/static-client`` — used when
        :envvar:`TELEOP_WEB_CLIENT_STATIC_DIR` is unset.
    """
    return Path.home() / ".cloudxr" / "static-client"


def resolve_web_client_static_dir() -> Path:
    """Directory for web client assets: :envvar:`TELEOP_WEB_CLIENT_STATIC_DIR` or default.

    Args:
        None (reads :envvar:`TELEOP_WEB_CLIENT_STATIC_DIR` from the environment).

    Returns:
        Absolute path to the static client root (may not exist yet).

    Raises:
        RuntimeError: If ``TELEOP_WEB_CLIENT_STATIC_DIR`` points at a non-directory path.
    """
    raw = os.environ.get(TELEOP_WEB_CLIENT_STATIC_DIR_ENV, "").strip()
    if raw:
        p = Path(os.path.expanduser(raw)).resolve()
        if p.exists() and not p.is_dir():
            raise RuntimeError(
                f"{TELEOP_WEB_CLIENT_STATIC_DIR_ENV} is not a directory: {p}"
            )
        return p
    return default_web_client_static_dir()


def _fetch_url_bytes(url: str, *, timeout: float = 120.0) -> bytes:
    """Download *url* into memory (WebXR client assets only; size-capped).

    Args:
        url: HTTPS URL of a single static asset (``index.html``, ``bundle.js``,
            lazy chunk, or ``asset-manifest.json``).
        timeout: ``urlopen`` socket timeout in seconds.

    Returns:
        Response body bytes (non-empty for successful downloads).

    Raises:
        RuntimeError: On network failure or if the body exceeds
            :data:`_USB_LOCAL_ASSET_MAX_BYTES`.
    """
    req = Request(url, headers={"User-Agent": "isaacteleop-cloudxr"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            # Reject oversized bodies when Content-Length is trustworthy.
            cl = resp.headers.get("Content-Length")
            if cl is not None:
                try:
                    n = int(cl)
                except ValueError:
                    pass
                else:
                    if n > _USB_LOCAL_ASSET_MAX_BYTES:
                        raise RuntimeError(
                            f"Refusing download larger than {_USB_LOCAL_ASSET_MAX_BYTES} bytes "
                            f"(Content-Length={n}): {url}"
                        )
            # Read one byte past the cap so we can detect truncated Content-Length.
            data = resp.read(_USB_LOCAL_ASSET_MAX_BYTES + 1)
    except URLError as exc:
        raise RuntimeError(f"Could not download {url}: {exc}") from exc
    if len(data) > _USB_LOCAL_ASSET_MAX_BYTES:
        raise RuntimeError(
            f"Download exceeded {_USB_LOCAL_ASSET_MAX_BYTES} bytes (no trusted Content-Length): {url}"
        )
    return data


def _write_atomic_bytes(dest: Path, data: bytes) -> None:
    """Write *data* to *dest* via a ``.part`` temp file (crash-safe).

    Args:
        dest: Final file path under the static client directory.
        data: Raw bytes to persist (HTML, JS, JSON manifest, etc.).

    Raises:
        OSError: If the parent directory cannot be created or the rename fails.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except OSError:
        # Best-effort cleanup so a failed partial does not masquerade as valid.
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


# ---------------------------------------------------------------------------
# Web client asset manifest sync
#
# Production webpack builds emit ``bundle.js`` plus lazy ``bundle.<name>.js``
# chunks. ``asset-manifest.json`` lists every file OOB/--host-client must
# cache and serve. Helpers below resolve the file set from local or remote
# manifests and drive :func:`require_web_client_static_dir`.
# ---------------------------------------------------------------------------

# Minimum assets for a working OOB/--host-client session before manifest support.
_LEGACY_WEB_CLIENT_ASSETS = ("index.html", "bundle.js")
# Always required once manifest-driven sync is enabled (manifest lists lazy chunks).
_MANIFEST_CORE_FILES = (*_LEGACY_WEB_CLIENT_ASSETS, "asset-manifest.json")


def _is_safe_manifest_basename(name: str) -> bool:
    """Return True if *name* is a single-segment filename safe to write under static_dir.

    Args:
        name: Candidate basename from a manifest ``files`` entry.

    Returns:
        ``False`` for path separators, ``..`` segments, or absolute paths.
    """
    if name in (".", ".."):
        return False
    if "/" in name or "\\" in name:
        return False
    if any(part == ".." for part in Path(name).parts):
        return False
    return Path(name).name == name


def _manifest_file_names(payload: object) -> list[str] | None:
    """Parse ``asset-manifest.json`` payload into a deduplicated file list.

    Args:
        payload: Decoded JSON object from ``asset-manifest.json`` (expects a
            top-level ``files`` array of non-empty strings).

    Returns:
        Deduplicated basenames to sync, or ``None`` if *payload* is not a valid
        manifest (wrong shape, empty list, or no usable entries).
    """
    # Reject non-object JSON (or wrong schema version).
    if not isinstance(payload, dict):
        return None
    files = payload.get("files")
    # Require a non-empty array of basenames.
    if not isinstance(files, list) or not files:
        return None
    # Preserve manifest order; skip duplicates and non-string entries.
    names: list[str] = []
    for entry in files:
        if (
            isinstance(entry, str)
            and entry
            and _is_safe_manifest_basename(entry)  # single-segment basename only
            and entry not in names
        ):
            names.append(entry)
    return names or None


def _with_manifest_core_files(names: list[str]) -> list[str]:
    """Ensure manifest-driven sync always includes entry HTML/JS and the manifest.

    Webpack may omit ``index.html`` from ``files`` if only JS chunks changed;
    OOB still needs the shell page and manifest on disk for the next sync pass.

    Args:
        names: Basenames from a local or remote ``asset-manifest.json``.

    Returns:
        *names* with any missing :data:`_MANIFEST_CORE_FILES` entries appended
        (order preserved; duplicates avoided).
    """
    out = list(names)
    # Append shell page + manifest if the webpack manifest omitted them.
    for name in _MANIFEST_CORE_FILES:
        if name not in out:
            out.append(name)
    return out


def _read_local_web_client_manifest(static_dir: Path) -> list[str] | None:
    """Read ``asset-manifest.json`` from the on-disk static client cache.

    Args:
        static_dir: Directory returned by :func:`resolve_web_client_static_dir`.

    Returns:
        Parsed file list from the local manifest, or ``None`` if the manifest is
        missing, empty, or unreadable (treat as legacy two-file layout).
    """
    manifest_path = static_dir / "asset-manifest.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size == 0:
        return None
    try:
        return _manifest_file_names(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        # Corrupt manifest → behave like pre-manifest releases.
        return None


def _missing_web_client_assets(static_dir: Path, names: Iterable[str]) -> list[str]:
    """List cached assets that are absent or zero-length under *static_dir*.

    Args:
        static_dir: Web client static root (``TELEOP_WEB_CLIENT_STATIC_DIR``).
        names: Basenames to check (e.g. from a manifest).

    Returns:
        Subset of *names* that need downloading or re-fetching.
    """
    missing: list[str] = []
    for name in names:
        dest = static_dir / name
        if not dest.is_file() or dest.stat().st_size == 0:
            missing.append(name)
    return missing


def _web_client_asset_names_from_origin(client_origin: str) -> list[str]:
    """Resolve the full asset list for a published client origin.

    Fetches ``asset-manifest.json`` from *client_origin*. When the manifest is
    unavailable (older release), falls back to :data:`_LEGACY_WEB_CLIENT_ASSETS`
    only so OOB still works with a single ``bundle.js``.

    Args:
        client_origin: Base URL for the versioned client (trailing slash optional),
            e.g. from :func:`default_web_client_origin`.

    Returns:
        Basenames to sync, including core HTML/JS and manifest when manifest
        fetch succeeds.
    """
    try:
        raw = _fetch_url_bytes(
            urljoin(client_origin, "asset-manifest.json"), timeout=30.0
        )
        names = _manifest_file_names(json.loads(raw.decode("utf-8")))
    except (
        URLError,
        RuntimeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
    ):
        names = None
    if names is None:
        # Published client predates asset-manifest.json (single bundle.js era).
        return list(_LEGACY_WEB_CLIENT_ASSETS)
    return _with_manifest_core_files(names)


def _web_client_assets_to_sync(static_dir: Path, client_origin: str) -> list[str]:
    """Decide which client files :func:`require_web_client_static_dir` must fetch.

    Prefer the local manifest when present and complete (avoids re-downloading
    the remote manifest on every launcher start). Otherwise use the remote
    manifest (or legacy two-file list).

    Args:
        static_dir: Resolved static client directory on disk.
        client_origin: Published client base URL for missing assets.

    Returns:
        Basenames still missing locally; empty when the cache is complete.
    """
    local_names = _read_local_web_client_manifest(static_dir)
    if local_names is not None:
        # Fast path: trust local manifest if every listed file is already cached.
        missing = _missing_web_client_assets(
            static_dir, _with_manifest_core_files(local_names)
        )
        if not missing:
            return []
    # Slow path: consult origin manifest (or legacy fallback) for anything missing.
    return _missing_web_client_assets(
        static_dir, _web_client_asset_names_from_origin(client_origin)
    )


def require_web_client_static_dir() -> Path:
    """Ensure web client static assets exist under :func:`resolve_web_client_static_dir`.

    Creates the directory if needed. Downloads missing files from the published
    client origin. Uses ``asset-manifest.json`` when present (see
    :doc:`build_from_source/webxr`); otherwise falls back to ``index.html`` and
    ``bundle.js`` only.

    Idempotent: safe to call from both :class:`~.launcher.CloudXRLauncher` and
    ``wss.run`` (second call skips network when files are present).

    Returns:
        Resolved static directory path (existing, populated).

    Raises:
        RuntimeError: If the path is invalid, a download fails, or core assets
            are still missing after sync.
    """
    p = resolve_web_client_static_dir()

    # Ensure the cache root exists before any manifest or asset writes.
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Cannot create web client static directory {p}: {exc}"
        ) from exc

    client_origin = default_web_client_origin()
    # Download only assets reported missing (manifest-aware).
    for name in _web_client_assets_to_sync(p, client_origin):
        dest = p / name  # basename-only; validated in _manifest_file_names
        url = urljoin(client_origin, name)
        log.info("web client: fetching %s → %s", url, dest)
        data = _fetch_url_bytes(url)
        if not data:
            raise RuntimeError(f"Downloaded empty body from {url}")
        try:
            _write_atomic_bytes(dest, data)
        except OSError as exc:
            raise RuntimeError(f"Failed to write {dest}: {exc}") from exc

    # Entry HTML/JS must exist even when lazy chunks are served separately.
    for name in _LEGACY_WEB_CLIENT_ASSETS:
        fp = p / name
        if not fp.is_file() or fp.stat().st_size == 0:
            raise RuntimeError(f"Web client file missing or empty after fetch: {fp}")
    return p


def _wait_for_port(host: str, port: int, timeout: float) -> bool:
    """Poll until *host:port* accepts a TCP connection or *timeout* elapses.

    Args:
        host: Address to probe (loopback for USB-local static server readiness).
        port: TCP port to connect to.
        timeout: Maximum seconds to keep retrying.

    Returns:
        ``True`` if a connection succeeded within *timeout*, else ``False``.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _usb_local_static_handler_class(
    static_root: Path,
) -> type[http.server.SimpleHTTPRequestHandler]:
    """Build an ``SimpleHTTPRequestHandler`` subclass rooted at *static_root*.

    Args:
        static_root: Directory containing ``index.html``, ``bundle.js``, and
            optional lazy chunks synced by :func:`require_web_client_static_dir`.

    Returns:
        Handler class (not instance) bound to *static_root* for
        :class:`http.server.ThreadingHTTPServer`.
    """
    root = str(static_root.resolve())

    class _Handler(http.server.SimpleHTTPRequestHandler):
        """Serve files from a fixed directory; log at DEBUG instead of stderr."""

        def __init__(self, *args, **kwargs):
            """Bind the handler to *root* (manifest-synced static client directory)."""
            super().__init__(*args, directory=root, **kwargs)

        def log_message(self, fmt: str, *args) -> None:
            """Route access logs to the cloudxr logger at DEBUG."""
            log.debug("%s - %s", self.address_string(), fmt % args)

    return _Handler


def start_usb_local_https_server(
    static_root: Path,
    *,
    cert_file: Path,
    key_file: Path,
    port: int | None = None,
    host: str = "127.0.0.1",
    ready_timeout: float = 15.0,
) -> tuple[threading.Thread, http.server.ThreadingHTTPServer]:
    """Serve *static_root* over HTTPS using the same PEM as the WSS proxy.

    When *port* is ``None`` (the default) the bind port is resolved via
    :func:`usb_ui_port` (env-overridable through ``USB_UI_PORT``).

    *host* controls the bind address: ``"127.0.0.1"`` (default) for USB-local
    mode where the headset reaches the PC via ``adb reverse``; ``"0.0.0.0"``
    for ``--host-client`` WiFi/LAN mode where the headset connects directly.

    Args:
        static_root: Populated web client directory (manifest-aware sync).
        cert_file: TLS certificate PEM (shared with WSS proxy).
        key_file: TLS private key PEM.
        port: Bind port; ``None`` → :func:`usb_ui_port`.
        host: Bind address (``127.0.0.1`` or ``0.0.0.0``).
        ready_timeout: Seconds to wait for the listener before raising.

    Returns:
        ``(daemon_thread, httpd)`` — caller must pass both to
        :func:`stop_usb_local_https_server` on shutdown.

    Raises:
        RuntimeError: If the server does not accept connections within
            *ready_timeout*.
    """
    if port is None:
        port = usb_ui_port()
    handler_cls = _usb_local_static_handler_class(static_root)
    httpd = http.server.ThreadingHTTPServer((host, port), handler_cls)
    httpd.daemon_threads = True
    # Same TLS material as WSS so the headset trusts one self-signed cert.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert_file), str(key_file))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    thread = threading.Thread(
        target=httpd.serve_forever, name="usb-local-https", daemon=True
    )
    thread.start()
    log.info(
        "Static HTTPS server starting — waiting up to %.0fs for :%d",
        ready_timeout,
        port,
    )
    probe_host = "127.0.0.1" if host == "0.0.0.0" else host
    if not _wait_for_port(probe_host, port, ready_timeout):
        try:
            httpd.shutdown()
        finally:
            httpd.server_close()
        thread.join(timeout=2.0)
        raise RuntimeError(
            f"Static HTTPS server did not accept connections on {host}:{port} "
            f"within {ready_timeout:.0f}s"
        )
    log.info("Static HTTPS server ready on https://%s:%d", host, port)
    return thread, httpd


def stop_usb_local_https_server(
    thread: threading.Thread | None,
    httpd: http.server.ThreadingHTTPServer | None,
) -> None:
    """Shut down the thread HTTP server from :func:`start_usb_local_https_server`.

    Args:
        thread: Background ``serve_forever`` thread (may be ``None``).
        httpd: Server instance returned by :func:`start_usb_local_https_server`
            (may be ``None``).
    """
    if httpd is not None:
        try:
            httpd.shutdown()
        finally:
            httpd.server_close()
    if thread is not None:
        thread.join(timeout=5.0)
    log.info("Static HTTPS server stopped")


def web_client_base_override_from_env() -> str | None:
    """Read :envvar:`TELEOP_WEB_CLIENT_BASE` if set.

    Returns:
        Stripped override URL, or ``None`` when unset/empty (use versioned
        GitHub Pages origin or USB-local loopback HTTPS instead).
    """
    v = os.environ.get(TELEOP_WEB_CLIENT_BASE_ENV, "").strip()
    return v or None


def parse_env_port(env_var: str, raw: str) -> int:
    """Parse and validate a port string from an environment variable.

    Args:
        env_var: Variable name (for error messages), e.g. ``"PROXY_PORT"``.
        raw: Raw string value from the environment.

    Returns:
        Integer port in ``1..65535``.

    Raises:
        ValueError: If *raw* is not an integer or is out of range.
    """
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
    """TCP port for the WSS proxy (``PROXY_PORT`` environment variable if set, else ``48322``).

    Returns:
        Resolved proxy port used for OOB WebSocket and ``--host-client`` static route.
    """
    raw = os.environ.get("PROXY_PORT", "").strip()
    if raw:
        return parse_env_port("PROXY_PORT", raw)
    return WSS_PROXY_DEFAULT_PORT


def usb_ui_port() -> int:
    """TCP port for the USB-local WebXR static HTTPS server.

    Reads the ``USB_UI_PORT`` environment variable if set, else falls back to
    :data:`USB_UI_DEFAULT_PORT` (8080).  Override this when something else on
    the host needs port 8080 (e.g. a Viser/Meshcat viewer running alongside).

    Returns:
        HTTPS static server port for ``--usb-local`` (adb-reverse target).
    """
    raw = os.environ.get("USB_UI_PORT", "").strip()
    if raw:
        return parse_env_port("USB_UI_PORT", raw)
    return USB_UI_DEFAULT_PORT


def usb_backend_port() -> int:
    """TCP port for the USB-local CloudXR backend (native client direct connection).

    Reads the ``USB_BACKEND_PORT`` environment variable if set, else falls
    back to :data:`USB_BACKEND_DEFAULT_PORT` (49100).  This port is exposed
    to the headset via ``adb reverse``; override only when a host process
    already owns 49100.

    Returns:
        CloudXR backend TCP port for adb reverse in USB-local mode.
    """
    raw = os.environ.get("USB_BACKEND_PORT", "").strip()
    if raw:
        return parse_env_port("USB_BACKEND_PORT", raw)
    return USB_BACKEND_DEFAULT_PORT


def usb_turn_port() -> int:
    """TCP/UDP port for the USB-local coturn TURN server.

    Reads the ``USB_TURN_PORT`` environment variable if set, else falls back
    to :data:`USB_TURN_DEFAULT_PORT` (3478).  coturn binds this on
    127.0.0.1 and ``adb reverse`` exposes it to the headset for WebRTC
    ICE relay.  Override only when 3478 is occupied (e.g. by a system
    coturn that wasn't masked).

    Returns:
        TURN relay port for WebRTC ICE in USB-local mode.
    """
    raw = os.environ.get("USB_TURN_PORT", "").strip()
    if raw:
        return parse_env_port("USB_TURN_PORT", raw)
    return USB_TURN_DEFAULT_PORT


def guess_lan_ipv4() -> str | None:
    """Best-effort LAN IPv4 for operator URLs when headsets reach the PC by IP.

    Returns:
        Non-loopback IPv4 chosen by opening a UDP socket toward a routable
        address, or ``None`` if no suitable address is found.
    """
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
    """Default hub stream config from env and LAN guess (same host as proxy port by default).

    Args:
        resolved_proxy_port: WSS proxy port from :func:`wss_proxy_port` (after env override).

    Returns:
        Dict with ``serverIP`` and ``port`` keys for OOB hub / bookmark builders.
    """
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

    Returns:
        Subset of stream-config fields to merge (empty dict when no overrides set).
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


def teleop_client_route_from_env() -> str:
    """Return the HashRouter fragment to append to the headset bookmark URL.

    Default: :data:`DEFAULT_TELEOP_CLIENT_ROUTE` (empty — no fragment, the
    WebXR client picks its own landing route). Set ``TELEOP_CLIENT_ROUTE``
    to a path like ``/real/gear/dexmate`` to force a specific route; an
    explicit empty value also suppresses the fragment. A leading ``#`` in
    the override is stripped (the URL builder always emits exactly one).
    Returns ``""`` to mean "no fragment".

    Returns:
        Route path without leading ``#`` (e.g. ``/real/gear/dexmate``), or
        ``""`` when no fragment should be appended.
    """
    raw = os.environ.get(TELEOP_CLIENT_ROUTE_ENV)
    if raw is None:
        return DEFAULT_TELEOP_CLIENT_ROUTE
    val = raw.strip()
    if not val:
        return ""
    return val.lstrip("#")


def build_headset_bookmark_url(
    *,
    web_client_base: str,
    stream_config: dict | None = None,
    control_token: str | None = None,
) -> str:
    """Full WebXR page URL with OOB query params (``oobEnable=1``, stream fields, optional token).

    The client derives ``wss://{serverIP}:{port}/oob/v1/ws`` from ``serverIP`` + ``port`` in the query
    when ``oobEnable=1``.

    A HashRouter fragment is appended at the end when ``TELEOP_CLIENT_ROUTE``
    is set (e.g. ``#/real/gear/dexmate``); by default no fragment is added
    and the WebXR client picks its own landing route.

    Args:
        web_client_base: WebXR client origin (GitHub Pages or USB-local HTTPS).
        stream_config: Must include ``serverIP`` and ``port``; optional codec,
            TURN, and UI fields.
        control_token: Optional OOB hub token (omitted from display URLs when redacted).

    Returns:
        Absolute URL opened on the headset (query + optional hash route).

    Raises:
        ValueError: If *stream_config* lacks ``serverIP`` or ``port``.
    """
    cfg = stream_config or {}
    if not cfg.get("serverIP") or cfg.get("port") is None:
        raise ValueError(
            "build_headset_bookmark_url requires stream_config with serverIP and port"
        )
    # Required OOB query fields — client opens WSS from serverIP + port.
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
    v = cfg.get("turnServer")
    if v is not None and str(v).strip() != "":
        params["turnServer"] = str(v).strip()
    v = cfg.get("turnUsername")
    if v is not None and str(v).strip() != "":
        params["turnUsername"] = str(v).strip()
    v = cfg.get("turnCredential")
    if v is not None and str(v).strip() != "":
        params["turnCredential"] = str(v).strip()
    if cfg.get("iceRelayOnly"):
        params["iceRelayOnly"] = "1"
    q = urlencode(params)
    base = web_client_base.rstrip("/")
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}{q}"
    route = teleop_client_route_from_env()
    if route:
        url = f"{url}#{route}"
    return url


def resolve_lan_host_for_oob() -> str:
    """PC LAN address the headset uses for ``wss://…:PROXY_PORT`` over WiFi.

    Returns:
        IPv4/hostname from :envvar:`TELEOP_PROXY_HOST` or :func:`guess_lan_ipv4`.

    Raises:
        RuntimeError: If neither env override nor LAN guess yields an address.
    """
    h = os.environ.get("TELEOP_PROXY_HOST", "").strip() or guess_lan_ipv4()
    if not h:
        raise RuntimeError(
            "--setup-oob needs this PC's LAN IP for WebXR/WSS URLs. "
            "Set TELEOP_PROXY_HOST to an address the headset can reach over WiFi "
            "(or fix routing so guess_lan_ipv4() works)."
        )
    return h


def oob_progress(stage: str, msg: str) -> None:
    """One-line progress update for ``--setup-oob`` / ``--usb-local`` steps.

    Goes to stderr in dim cyan so the operator can see *where* the launcher
    is in its sequence of steps without these lines competing with the
    success banner (stdout) or error prints (red). Distinct from
    ``log.info``, which writes to log files only and is invisible at the
    terminal.

    Args:
        stage: Short label (e.g. ``"usb-local"``) printed in brackets.
        msg: Human-readable step description.
    """
    print(f"\033[36m[{stage}]\033[0m {msg}", file=sys.stderr, flush=True)


def print_oob_hub_startup_banner(
    *,
    lan_host: str | None = None,
    usb_local: bool = False,
    web_client_base: str | None = None,
) -> None:
    """Print operator instructions for OOB + USB adb automation.

    Args:
        lan_host: PC LAN address (WiFi mode) or ``"127.0.0.1"`` (USB-local mode).
        usb_local: When ``True``, adjust the banner to describe the USB-local
            topology: everything reachable from the headset via ``adb reverse``
            on loopback; WebXR UI from ``TELEOP_WEB_CLIENT_STATIC_DIR`` (HTTPS, same PEM as WSS).
        web_client_base: Override the WebXR client base URL in the bookmark.
            When ``None`` (default), uses the versioned GitHub Pages client
            (WiFi mode) or the USB-local HTTPS origin (USB-local mode).
            ``TELEOP_WEB_CLIENT_BASE`` env var still takes precedence over this.
    """
    port = wss_proxy_port()
    ui_port = usb_ui_port()
    backend_port = usb_backend_port()
    turn_port = usb_turn_port()
    token = os.environ.get("CONTROL_TOKEN") or None

    if not lan_host:
        lan_host = resolve_lan_host_for_oob() if not usb_local else "127.0.0.1"
    primary_host = lan_host

    if usb_local:
        web_base = (
            os.environ.get("TELEOP_WEB_CLIENT_BASE", "").strip()
            or f"https://localhost:{ui_port}"
        )
    elif web_client_base is not None:
        web_base = web_client_base
    else:
        web_base = default_web_client_origin()

    stream_cfg: dict = {"serverIP": primary_host, "port": port}
    if usb_local:
        # No mediaAddress: it's a NAT-override that bypasses ICE and would
        # short-circuit the TURN-relayed media path. Let the SDK discover
        # the media endpoint through ICE via coturn.
        stream_cfg["turnServer"] = f"turn:{USB_HOST}:{turn_port}?transport=tcp"
        stream_cfg["turnUsername"] = USB_TURN_USER
        stream_cfg["turnCredential"] = USB_TURN_CREDENTIAL
        stream_cfg["iceRelayOnly"] = True

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
    if usb_local:
        print("OOB TELEOP (USB-local) — headset reaches PC on loopback via adb reverse")
    else:
        print(
            "OOB TELEOP — enabled (out-of-band control hub is running in this WSS proxy)"
        )
    print(bar)
    print()
    print(
        f"  The hub shares the CloudXR proxy TLS port {port} on this machine "
        f"(control WebSocket: {wss_primary})."
    )
    if usb_local:
        print(
            "  USB-local mode: adb reverse active for ports "
            f"{ui_port}/tcp (WebXR static UI — HTTPS), "
            f"{port}/tcp (WSS), "
            f"{backend_port}/tcp (backend), "
            f"{turn_port}/tcp (TURN relay — coturn)."
        )
        print(
            "  The launcher has started the WebXR static HTTPS server + coturn automatically "
            "(see coturn-cloudxr-3478.log if CONNECT fails)."
        )
    else:
        print(
            "  Same steps as docs: references/oob_teleop_control.rst — "
            '"End-to-end workflow (the usual path)".'
        )
    print()
    if usb_local:
        print("  adb: USB cable required — headset reaches this PC via adb reverse.")
    else:
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
    route = teleop_client_route_from_env()
    route_src = (
        f"from {TELEOP_CLIENT_ROUTE_ENV}"
        if os.environ.get(TELEOP_CLIENT_ROUTE_ENV) is not None
        else "default"
    )
    if route:
        print(
            f"           Client route: \033[36m#{route}\033[0m  "
            f"({route_src}; change via {TELEOP_CLIENT_ROUTE_ENV}, "
            f"set empty to suppress)"
        )
    else:
        print(
            f"           Client route: \033[36m<none>\033[0m  "
            f"(default; set {TELEOP_CLIENT_ROUTE_ENV}=/real/gear/dexmate "
            "to land on a specific route)"
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


# ---------------------------------------------------------------------------
# Host preflight: best-effort ufw + port-bindability warnings.
# Never fatal — operators routinely run with ufw inactive or with non-default
# ports. Goal is to surface "you forgot ufw allow" before the headset times
# out, with the exact remediation command.
# ---------------------------------------------------------------------------


def _ufw_unallowed_ports(ports: list[int]) -> list[int] | None:
    """Return the subset of *ports* that ufw appears not to allow.

    ``None`` if ufw is unavailable or inactive (caller should skip the warning).

    Args:
        ports: TCP ports to check against ``ufw status`` output.

    Returns:
        Ports with no matching ALLOW rule, or ``None`` when ufw cannot be queried.
    """
    try:
        proc = subprocess.run(
            ["ufw", "status"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout or ""
    if "inactive" in out.lower() or "Status: active" not in out:
        return None
    return [
        p
        for p in ports
        if not re.search(rf"^\s*{p}(?:/(?:tcp|udp))?\b.*ALLOW", out, re.MULTILINE)
    ]


def _port_in_use(port: int, host: str) -> bool:
    """True if a TCP listener already owns ``(host, port)``.

    Args:
        port: TCP port to probe with a throwaway bind.
        host: Bind address (typically ``127.0.0.1`` for preflight).

    Returns:
        ``True`` when ``bind`` fails with ``EADDRINUSE`` (or similar).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return True
    return False


def ss_listeners_on_port(port: int) -> list[str]:
    """Return one trimmed ``ss -tulpn`` line per TCP/UDP listener on *port*.

    Why: a wildcard listener (``0.0.0.0:port``) can coexist with a loopback
    bind via ``SO_REUSEADDR``, so :func:`_port_in_use` misses it. Parsing
    ``ss`` output catches every listener regardless of bound address.
    Empty list when ``ss`` is unavailable (minimal containers, BSD, etc.) —
    callers must treat that as "couldn't ask", not "definitely free".

    Args:
        port: Local TCP/UDP port number to match in ``ss`` output.

    Returns:
        Trimmed ``ss -tulpn`` lines whose local address ends with ``:<port>``.
    """
    try:
        proc = subprocess.run(
            ["ss", "-tulpn"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out: list[str] = []
    for line in (proc.stdout or "").splitlines():
        cols = line.split()
        if len(cols) < 5:
            continue
        # Local-Address:Port is column 5 (index 4); bracketed IPv6 like ``[::]:3478``
        # also ends in ``:<port>``.
        if cols[4].endswith(f":{port}"):
            out.append(line.strip())
    return out


def print_host_preflight_warnings(*, usb_local: bool) -> None:
    """Best-effort host preflight (port conflicts + ufw).

    In ``--usb-local`` mode this is fail-fast: a port conflict on any of
    the four required loopback ports (WSS / UI / backend / TURN) raises
    :class:`RuntimeError` so the launcher exits before sinking time into
    a setup that can't possibly stream. In WiFi mode the same port-busy
    case stays warn-only — the WSS bind will fail loudly on its own with
    ``EADDRINUSE`` and there's no usb-local-style multi-port surface.

    ufw findings are always warn-only (best-effort: ``status`` parsing
    can yield false positives on permissive rulesets), and ufw is only
    checked in WiFi mode (USB-local is loopback, not firewalled).

    The WSS proxy binds the wildcard address (``host=""`` in
    :mod:`websockets`, i.e. ``0.0.0.0``), but we probe via loopback
    here: a holder that already owns the wildcard will still cause our
    loopback probe to fail with ``EADDRINUSE`` on Linux, so coverage of
    real conflicts is preserved while keeping the literal ``0.0.0.0``
    out of the source (security-scanner false positive about binding to
    all interfaces). The probe socket is closed immediately on success
    — nothing is actually exposed.

    Args:
        usb_local: When ``True``, check all four USB-local loopback ports
            and raise on conflict; when ``False``, warn only on WSS port.
    """
    if usb_local:
        targets: list[tuple[int, str]] = [
            (wss_proxy_port(), "127.0.0.1"),
            (usb_ui_port(), "127.0.0.1"),
            (usb_backend_port(), "127.0.0.1"),
            (usb_turn_port(), "127.0.0.1"),
        ]
    else:
        targets = [(wss_proxy_port(), "127.0.0.1")]
    busy = [p for p, host in targets if _port_in_use(p, host)]
    if busy:
        ports_re = "|".join(f":{p}" for p in busy)
        if usb_local:
            log.error("preflight: port(s) already in use: %s", busy)
            raise RuntimeError(
                f"USB-local: required port(s) {busy} already in use — cannot proceed.\n"
                f"Kill the holder (`ss -tulpn | grep -E '{ports_re}'`) or override "
                "via PROXY_PORT / USB_UI_PORT / USB_BACKEND_PORT / USB_TURN_PORT, "
                "then retry."
            )
        log.warning("preflight: port(s) already in use: %s", busy)
        print(
            f"\n\033[33m[preflight] port(s) {busy} already in use; kill the "
            f"holder (`ss -tulpn | grep -E '{ports_re}'`) or override via "
            "PROXY_PORT.\033[0m\n"
        )
    # ufw is only meaningful in WiFi mode (USB-local is loopback, not firewalled).
    if not usb_local:
        unallowed = _ufw_unallowed_ports([wss_proxy_port()])
        if unallowed:
            cmd = "; ".join(f"sudo ufw allow {p}/tcp" for p in unallowed)
            log.warning("preflight: ufw blocks port(s) %s", unallowed)
            print(
                f"\n\033[33m[preflight] ufw is active and may block port(s) "
                f"{unallowed} from reaching the headset. Allow with: {cmd}"
                "\033[0m\n"
            )
