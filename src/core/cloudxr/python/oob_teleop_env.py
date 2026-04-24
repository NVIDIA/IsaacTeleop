# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OOB teleop environment: proxy port, LAN detection, stream defaults, headset bookmark URLs, startup banner."""

from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

from .oob_teleop_hub import OOB_WS_PATH

log = logging.getLogger("oob-teleop-env")

WSS_PROXY_DEFAULT_PORT = 48322

DEFAULT_WEB_CLIENT_ORIGIN = "https://nvidia.github.io/IsaacTeleop/client/"

TELEOP_WEB_CLIENT_BASE_ENV = "TELEOP_WEB_CLIENT_BASE"

CHROME_INSPECT_DEVICES_URL = "chrome://inspect/#devices"

# ---------------------------------------------------------------------------
# USB-local mode constants
#
# "USB-local" means: the headset reaches the PC over loopback (127.0.0.1) via
# `adb reverse`. The operator runs the webxr_client dev-server (`npm run
# dev-server:https`) on :USB_UI_PORT, and the Python launcher exposes the
# WSS proxy + CloudXR backend + coturn through `adb reverse` too.
# ---------------------------------------------------------------------------

USB_HOST = "127.0.0.1"  # serverIP seen by the headset (its own localhost)
USB_UI_PORT = 8080  # webxr_client dev-server port (webpack default)
USB_BACKEND_PORT = 49100  # CloudXR backend (native client direct connection)
USB_TURN_PORT = 3478  # coturn TURN server port (adb reverse'd to headset)
USB_TURN_USER = "cloudxr"  # TURN username
USB_TURN_CREDENTIAL = "cloudxrpass"  # TURN credential


# ---------------------------------------------------------------------------
# USB-local: auto-orchestrate the webxr_client dev-server
# ---------------------------------------------------------------------------


class WebxrClientSetupError(RuntimeError):
    """Raised when the webxr_client dev-server cannot be prepared or started."""


def find_webxr_client_dir() -> Path | None:
    """Walk parents of this file for ``deps/cloudxr/webxr_client/``.

    Returns the absolute path when found (source checkout), or ``None``
    when running from an installed wheel that doesn't ship the source tree.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "deps" / "cloudxr" / "webxr_client"
        if candidate.is_dir() and (candidate / "package.json").is_file():
            return candidate
    return None


def _webxr_install_up_to_date(webxr_client_dir: Path) -> bool:
    """Check whether ``npm install`` can be skipped.

    Skip when ``node_modules/`` exists AND ``package-lock.json`` has not been
    modified since the directory was last populated.  This avoids a ~30s no-op
    on every subsequent launcher start.
    """
    node_modules = webxr_client_dir / "node_modules"
    lockfile = webxr_client_dir / "package-lock.json"
    if not node_modules.is_dir() or not lockfile.is_file():
        return False
    try:
        return node_modules.stat().st_mtime >= lockfile.stat().st_mtime
    except OSError:
        return False


def _run_subprocess_streaming(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    log_path: Path | None = None,
    tag: str,
) -> int:
    """Run *cmd* synchronously, streaming stdout+stderr to *log_path* if given.

    Returns the process return code.  Never raises on non-zero exit; callers
    decide whether that's fatal.
    """
    log.info("%s: %s  (cwd=%s)", tag, " ".join(cmd), cwd or os.getcwd())
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(log_path, "ab", buffering=0)
    else:
        out = subprocess.DEVNULL
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=out,
            stderr=subprocess.STDOUT,
            check=False,
        )
    finally:
        if log_path is not None:
            out.close()
    return proc.returncode


def ensure_webxr_client_ready(
    webxr_client_dir: Path,
    *,
    log_dir: Path | None = None,
) -> None:
    """Best-effort: download CloudXR SDK, then ``npm install`` + ``npm run build``.

    Steps:

    1. ``scripts/download_cloudxr_sdk.sh`` — warn-and-continue on failure
       (operators may have pre-staged the SDK tarballs themselves).
    2. ``npm install`` — required; raises :class:`WebxrClientSetupError` on
       failure.  Skipped when ``node_modules/`` is newer than
       ``package-lock.json`` (cached run).
    3. ``npm run build`` — required; raises on failure.

    Args:
        webxr_client_dir: Path to ``deps/cloudxr/webxr_client/``.
        log_dir: Directory for npm/build log files.  When ``None``, output
            is discarded.
    """
    repo_root = webxr_client_dir.parents[2]
    npm = shutil.which("npm")
    if npm is None:
        raise WebxrClientSetupError(
            "--usb-local: `npm` not found on PATH. Install Node.js LTS "
            "(https://nodejs.org/) so the webxr_client dev-server can run."
        )

    # Step 1: download CloudXR SDK (best-effort)
    sdk_script = repo_root / "scripts" / "download_cloudxr_sdk.sh"
    if sdk_script.is_file():
        rc = _run_subprocess_streaming(
            ["bash", str(sdk_script)],
            cwd=repo_root,
            log_path=(log_dir / "download_cloudxr_sdk.log") if log_dir else None,
            tag="SDK download",
        )
        if rc != 0:
            log.warning(
                "SDK download (%s) returned %d — continuing (SDK may already be staged)",
                sdk_script.name,
                rc,
            )
    else:
        log.info("SDK download: script not present at %s, skipping", sdk_script)

    # Step 2: npm install (cached when up-to-date)
    if _webxr_install_up_to_date(webxr_client_dir):
        log.info("npm install: skipped (node_modules up to date vs package-lock.json)")
    else:
        rc = _run_subprocess_streaming(
            [npm, "install"],
            cwd=webxr_client_dir,
            log_path=(log_dir / "npm_install.log") if log_dir else None,
            tag="npm install",
        )
        if rc != 0:
            raise WebxrClientSetupError(
                f"--usb-local: `npm install` in {webxr_client_dir} failed (exit {rc}). "
                f"See {log_dir / 'npm_install.log' if log_dir else 'npm output'}."
            )
        # Touch node_modules so the mtime cache reflects this successful install.
        try:
            os.utime(webxr_client_dir / "node_modules", None)
        except OSError:
            pass

    # Step 3: npm run build
    rc = _run_subprocess_streaming(
        [npm, "run", "build"],
        cwd=webxr_client_dir,
        log_path=(log_dir / "npm_build.log") if log_dir else None,
        tag="npm run build",
    )
    if rc != 0:
        raise WebxrClientSetupError(
            f"--usb-local: `npm run build` in {webxr_client_dir} failed (exit {rc}). "
            f"See {log_dir / 'npm_build.log' if log_dir else 'npm output'}."
        )


def _wait_for_port(host: str, port: int, timeout: float) -> bool:
    """Return ``True`` once *host:port* accepts a TCP connection, else ``False``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def start_webxr_dev_server(
    webxr_client_dir: Path,
    *,
    port: int = USB_UI_PORT,
    log_dir: Path | None = None,
    ready_timeout: float = 60.0,
) -> subprocess.Popen | None:
    """Spawn ``npm run dev-server:https`` and wait for *port* to accept TCP.

    The webpack dev-server compiles in-memory; no ``build/`` output is
    required.  Output is redirected to
    ``log_dir/webxr_dev_server.log`` (if *log_dir* given) so npm's noise
    doesn't pollute the main server log.

    Returns:
        The :class:`subprocess.Popen` handle on success.  Returns ``None``
        and logs a warning if the port does not open within *ready_timeout*
        seconds (the caller may still proceed; the operator can fall back to
        running the dev-server manually).
    """
    npm = shutil.which("npm")
    if npm is None:
        log.warning("start_webxr_dev_server: `npm` not on PATH")
        return None

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        server_log = log_dir / "webxr_dev_server.log"
        out = open(server_log, "ab", buffering=0)
    else:
        server_log = None
        out = subprocess.DEVNULL

    env = {**os.environ, "HTTPS": "true", "PORT": str(port)}
    try:
        proc = subprocess.Popen(
            [npm, "run", "dev-server:https"],
            cwd=str(webxr_client_dir),
            stdout=out,
            stderr=subprocess.STDOUT,
            env=env,
            # Start in a new process group so we can SIGTERM the whole tree
            # (npm -> node -> webpack-dev-server spawns children).
            start_new_session=True,
        )
    except OSError as exc:
        log.warning("webxr dev-server failed to start: %s", exc)
        return None
    finally:
        # The child inherited its own dup of the log fd via ``stdout=out``
        # and keeps writing to it; the parent doesn't need its copy past
        # this point (the subsequent ``_wait_for_port`` can hold for up
        # to ``ready_timeout`` seconds).  Close it here so we don't carry
        # a redundant fd through that wait or rely on refcount GC.
        if out is not subprocess.DEVNULL:
            try:
                out.close()
            except OSError:
                pass

    log.info(
        "webxr dev-server starting (pid=%d) — waiting up to %.0fs for :%d  (log: %s)",
        proc.pid,
        ready_timeout,
        port,
        server_log or "<discarded>",
    )
    if not _wait_for_port("127.0.0.1", port, ready_timeout):
        log.warning(
            "webxr dev-server did not open port %d within %.0fs — continuing; "
            "operator may need to start it manually "
            "(`cd %s && npm run dev-server:https`)",
            port,
            ready_timeout,
            webxr_client_dir,
        )
        # Return the Popen anyway so the caller can clean it up on shutdown.
        return proc

    log.info("webxr dev-server ready on https://127.0.0.1:%d", port)
    return proc


def stop_webxr_dev_server(proc: subprocess.Popen | None) -> None:
    """SIGTERM the dev-server process group, SIGKILL if it doesn't exit."""
    if proc is None or proc.poll() is not None:
        return
    import signal as _signal  # noqa: PLC0415

    try:
        os.killpg(proc.pid, _signal.SIGTERM)
    except OSError:
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, _signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
    log.info("webxr dev-server stopped")


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
    return f"{base}{sep}{q}"


# Query params on the bookmark URL that carry credentials and must never be
# echoed verbatim to logs/stdout. ``controlToken`` is the only true secret
# today (loaded from $CONTROL_TOKEN); ``turnUsername``/``turnCredential`` are
# currently public USB-local constants but are scrubbed for consistency and
# to stay correct if the values are ever rotated to per-session creds.
_REDACTED_BOOKMARK_PARAMS = ("controlToken", "turnUsername", "turnCredential")
_REDACTED_BOOKMARK_RE = re.compile(
    r"(" + "|".join(re.escape(k) for k in _REDACTED_BOOKMARK_PARAMS) + r")=[^&\s'\"]+"
)


def redact_bookmark_url(url_or_cmd: str) -> str:
    """Replace credential-bearing query params in ``url_or_cmd`` with ``<REDACTED>``.

    Safe to apply to either a bare URL or a shell-quoted command line that
    embeds one — only ``key=value`` substrings whose key is in
    :data:`_REDACTED_BOOKMARK_PARAMS` are touched.
    """
    return _REDACTED_BOOKMARK_RE.sub(r"\1=<REDACTED>", url_or_cmd)


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


def print_oob_hub_startup_banner(
    *, lan_host: str | None = None, usb_local: bool = False
) -> None:
    """Print operator instructions for OOB + USB adb automation.

    Args:
        lan_host: PC LAN address (WiFi mode) or ``"127.0.0.1"`` (USB-local mode).
        usb_local: When ``True``, adjust the banner to describe the USB-local
            topology: everything reachable from the headset via ``adb reverse``
            on loopback, webxr_client served by ``npm run dev-server:https``.
    """
    port = wss_proxy_port()
    token = os.environ.get("CONTROL_TOKEN") or None

    if not lan_host:
        lan_host = resolve_lan_host_for_oob() if not usb_local else "127.0.0.1"
    primary_host = lan_host

    if usb_local:
        web_base = (
            os.environ.get("TELEOP_WEB_CLIENT_BASE", "").strip()
            or f"https://localhost:{USB_UI_PORT}"
        )
    else:
        web_base = DEFAULT_WEB_CLIENT_ORIGIN

    stream_cfg: dict = {"serverIP": primary_host, "port": port}
    if usb_local:
        # No mediaAddress: it's a NAT-override that bypasses ICE and would
        # short-circuit the TURN-relayed media path. Let the SDK discover
        # the media endpoint through ICE via coturn.
        stream_cfg["turnServer"] = f"turn:{USB_HOST}:{USB_TURN_PORT}?transport=tcp"
        stream_cfg["turnUsername"] = USB_TURN_USER
        stream_cfg["turnCredential"] = USB_TURN_CREDENTIAL
        stream_cfg["iceRelayOnly"] = True

    web_client_base_override = web_client_base_override_from_env()
    if web_client_base_override:
        web_base = web_client_base_override

    stream_cfg = {**stream_cfg, **client_ui_fields_from_env()}

    primary_base = f"https://{primary_host}:{port}"
    bookmark_display = redact_bookmark_url(
        build_headset_bookmark_url(
            web_client_base=web_base,
            stream_config=stream_cfg,
            control_token=token,
        )
    )
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
            f"{USB_UI_PORT}/tcp (webxr_client dev-server), {port}/tcp (WSS), "
            f"{USB_BACKEND_PORT}/tcp (backend), "
            f"{USB_TURN_PORT}/tcp (TURN relay — coturn)."
        )
        print(
            "  The launcher has started the webxr_client dev-server + coturn "
            "automatically; see webxr_dev_server.log / coturn-cloudxr-3478.log "
            "if CONNECT fails."
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
    print()
    print("  Step 2 — Click CONNECT (CDP automation)")
    print("           CDP automation will click CONNECT via Chrome DevTools Protocol.")
    print(
        "           First-time setup on a new headset/browser is MANUAL: open the URL"
    )
    print("           above on the headset, accept the self-signed cert warning, grant")
    print("           the immersive-experience permission, and confirm CONNECT works.")
    print("           Once those are remembered, subsequent --setup-oob runs automate.")
    print(f"           Manual fallback: open {CHROME_INSPECT_DEVICES_URL},")
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
