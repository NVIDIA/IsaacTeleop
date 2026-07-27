# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Programmatic launcher for the CloudXR runtime and WSS proxy.

Wraps the logic from ``python -m isaacteleop.cloudxr`` into a reusable
start/stop API that can be called from embedding applications (e.g.
Isaac Lab Teleop) without requiring a separate terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import contextlib
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .env_config import EnvConfig
from .runtime import (
    RUNTIME_STARTUP_TIMEOUT_SEC,
    RUNTIME_TERMINATE_TIMEOUT_SEC,
    get_sdk_path,
    resolve_cloudxr_runtime_module,
    check_eula,
    wait_for_runtime_ready_sync,
)

logger = logging.getLogger(__name__)

DEFAULT_DEVICE_PROFILE = "Quest3"

_RUNTIME_WORKER_CODE = """\
import sys, os
sys.path = [p for p in sys.path if p]
from {runtime_mod}.runtime import run
run()
"""


class CloudXRLauncher:
    """Programmatic launcher for the CloudXR runtime and WSS proxy.

    Manages the full lifecycle of a CloudXR runtime process and its
    accompanying WSS TLS proxy.  The runtime and WSS proxy are started
    immediately on construction; use :meth:`stop` or the context
    manager protocol to shut them down.

    The runtime is launched as a fully isolated subprocess (via
    :class:`subprocess.Popen`) to avoid CUDA context conflicts with
    host applications like Isaac Sim that have already initialized GPU
    resources.

    Example::

        with CloudXRLauncher() as launcher:
            # runtime + WSS proxy are running
            ...

    Or with explicit stop::

        launcher = CloudXRLauncher(install_dir="~/.cloudxr")
        try:
            # ... use the running runtime ...
        finally:
            launcher.stop()
    """

    def __init__(
        self,
        install_dir: str = "~/.cloudxr",
        env_config: str | Path | None = None,
        device_profile: str = DEFAULT_DEVICE_PROFILE,
        accept_eula: bool = False,
        setup_oob: bool = False,
        usb_local: bool = False,
        host_client: bool = False,
        start_wss_proxy: bool = True,
    ) -> None:
        """Launch the CloudXR runtime and optionally the WSS proxy.

        Configures the environment, spawns the runtime subprocess, and
        optionally starts the WSS TLS proxy.  Blocks until the runtime
        signals readiness (up to
        :data:`~isaacteleop.cloudxr.runtime.RUNTIME_STARTUP_TIMEOUT_SEC`)
        or raises :class:`RuntimeError` on failure.

        Args:
            install_dir: CloudXR install directory.
            env_config: Optional path to a KEY=value env file for
                CloudXR env-var overrides.
            device_profile: CloudXR ``NV_DEVICE_PROFILE`` when not set in
                *env_config* or the process environment (default: Quest3).
            accept_eula: Accept the NVIDIA CloudXR EULA
                non-interactively.  When ``False`` and the EULA marker
                does not exist, the user is prompted on stdin.
            setup_oob: Enable the OOB teleop control hub and USB
                adb automation in the WSS proxy.
            usb_local: Route teleop traffic over USB headset loopback via
                ``adb reverse`` (requires *setup_oob*); also starts coturn
                for WebRTC ICE relay and serves WebXR static files
                (``TELEOP_WEB_CLIENT_STATIC_DIR`` or ``~/.cloudxr/static-client``,
                fetched from GitHub Pages if missing) over HTTPS.  Ports
                are overridable via ``USB_UI_PORT`` / ``USB_BACKEND_PORT``
                / ``USB_TURN_PORT``.
            host_client: Serve the web client at ``/client/`` on the WSS
                proxy port.  Assets are fetched once from GitHub Pages into
                ``TELEOP_WEB_CLIENT_STATIC_DIR`` or ``~/.cloudxr/static-client``.
            start_wss_proxy: Start the in-process WSS TLS proxy after the
                runtime is ready (default: ``True``).  Pass ``False`` when
                an external proxy is already running or only the runtime
                subprocess is needed.

        Raises:
            RuntimeError: If the EULA is not accepted or the runtime
                fails to start within the timeout.
            ValueError: If *start_wss_proxy* is ``False`` while any WSS-only
                option (*setup_oob*, *usb_local*, or *host_client*) is set.
        """
        self._install_dir = install_dir
        self._env_config = str(env_config) if env_config is not None else None
        self._device_profile = device_profile
        self._accept_eula = accept_eula
        self._setup_oob = setup_oob
        self._usb_local = usb_local
        self._host_client = host_client
        self._start_wss_proxy = start_wss_proxy

        if not self._start_wss_proxy and (
            self._setup_oob or self._usb_local or self._host_client
        ):
            raise ValueError(
                "start_wss_proxy=False is incompatible with setup_oob, "
                "usb_local, and host_client (those features require the WSS proxy)"
            )

        if self._usb_local or self._host_client:
            from .oob_teleop_env import require_web_client_static_dir  # noqa: PLC0415

            require_web_client_static_dir()

        self._runtime_proc: subprocess.Popen | None = None
        self._wss_thread: threading.Thread | None = None
        self._wss_loop: asyncio.AbstractEventLoop | None = None
        self._wss_stop_future: asyncio.Future | None = None
        self._wss_log_path: Path | None = None
        self._atexit_registered = False

        env_cfg = EnvConfig.from_args(
            self._install_dir,
            self._env_config,
            launcher_defaults={"NV_DEVICE_PROFILE": self._device_profile},
        )
        try:
            check_eula(accept_eula=self._accept_eula or None)
        except SystemExit as exc:
            raise RuntimeError(
                "CloudXR EULA was not accepted; cannot start the runtime"
            ) from exc
        logs_dir_path = env_cfg.ensure_logs_dir()

        self._cleanup_stale_runtime(env_cfg)

        # The worker imports asyncio (via isaacteleop.cloudxr.runtime), which imports
        # Python's ssl and loads the SYSTEM OpenSSL before the native stack dlopens the
        # bundled one. Two OpenSSL builds in one process crash (SIGSEGV) inside
        # SSL_CTX_use_certificate when the DTLS transport comes up on client connect.
        # LD_PRELOAD the bundled libraries so every OpenSSL symbol in the worker
        # resolves to the version libNvStreamServer.so was built against.
        worker_env = os.environ.copy()
        runtime_mod = resolve_cloudxr_runtime_module()
        sdk_dir = get_sdk_path()
        logger.info("CloudXR Runtime: module=%s sdk_path=%s", runtime_mod, sdk_dir)
        bundled_ssl = [
            os.path.join(sdk_dir, lib)
            for lib in ("libcrypto_nvst.so.3", "libssl_nvst.so.3")
        ]
        if all(os.path.isfile(lib) for lib in bundled_ssl):
            preload = " ".join(bundled_ssl)
            prev = worker_env.get("LD_PRELOAD")
            worker_env["LD_PRELOAD"] = f"{preload} {prev}" if prev else preload

        self._runtime_proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _RUNTIME_WORKER_CODE.format(runtime_mod=runtime_mod),
            ],
            env=worker_env,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        logger.info("CloudXR runtime process started (pid=%s)", self._runtime_proc.pid)

        if not wait_for_runtime_ready_sync(is_process_alive=self._is_runtime_alive):
            detail = self._collect_startup_failure_detail(logs_dir_path)
            self.stop()
            raise RuntimeError(
                "CloudXR runtime failed to start within "
                f"{RUNTIME_STARTUP_TIMEOUT_SEC}s.  {detail}"
            )
        logger.info("CloudXR runtime ready")

        if not self._atexit_registered:
            atexit.register(self.stop)
            self._atexit_registered = True

        if self._start_wss_proxy:
            wss_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
            wss_log_path = logs_dir_path / f"wss.{wss_ts}.log"
            self._wss_log_path = wss_log_path
            self._start_wss_proxy_thread(wss_log_path)
            logger.info("CloudXR WSS proxy started (log=%s)", wss_log_path)
        else:
            logger.info("CloudXR WSS proxy disabled; runtime only")

    # ------------------------------------------------------------------
    # CLI helpers for embedding applications and examples
    # ------------------------------------------------------------------

    @staticmethod
    def add_cloudxr_install_dir_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--cloudxr-install-dir`` on ``parser`` (default ``~/.cloudxr``)."""
        parser.add_argument(
            "--cloudxr-install-dir",
            type=str,
            default=os.path.expanduser("~/.cloudxr"),
            metavar="PATH",
            help="CloudXR install directory (default: ~/.cloudxr)",
        )

    @staticmethod
    def add_launch_cloudxr_runtime_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--launch-cloudxr-runtime`` on ``parser``.

        Uses :class:`argparse.BooleanOptionalAction`, so callers may pass
        ``--no-launch-cloudxr-runtime`` when the runtime is already running
        (for example after sourcing ``~/.cloudxr/run/cloudxr.env``).
        """
        parser.add_argument(
            "--launch-cloudxr-runtime",
            action=argparse.BooleanOptionalAction,
            default=True,
            help=(
                "Launch the CloudXR runtime and WSS proxy in-process before running "
                "(default: true). Pass --no-launch-cloudxr-runtime when the runtime is "
                "already running (e.g. after sourcing ~/.cloudxr/run/cloudxr.env)."
            ),
        )

    @staticmethod
    def add_cloudxr_device_profile_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--cloudxr-device-profile`` on ``parser`` (default Quest3)."""
        parser.add_argument(
            "--cloudxr-device-profile",
            type=str,
            default=DEFAULT_DEVICE_PROFILE,
            metavar="PROFILE",
            help=(
                "CloudXR NV_DEVICE_PROFILE for the runtime "
                f"(default: {DEFAULT_DEVICE_PROFILE}). "
                "Examples: Quest3, auto-webrtc, auto-native, AppleVisionPro. "
                "Overridden by --cloudxr-env-config or NV_DEVICE_PROFILE in the environment."
            ),
        )

    @staticmethod
    def add_cloudxr_env_config_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--cloudxr-env-config`` on ``parser`` (default: none).

        Points the launcher at a KEY=value env file of CloudXR runtime
        overrides (see the ``env_config`` argument of :meth:`__init__`).
        """
        parser.add_argument(
            "--cloudxr-env-config",
            type=str,
            default=None,
            metavar="PATH",
            help=(
                "Path to a KEY=value env file of CloudXR runtime overrides "
                "(default: none). Reserved keys (XR_RUNTIME_JSON, "
                "NV_CXR_RUNTIME_DIR, ...) are always computed and ignored if set."
            ),
        )

    @staticmethod
    def add_accept_eula_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--accept-eula`` on ``parser`` (default: false).

        When omitted and no acceptance marker exists, the launcher prompts
        on stdin before starting the runtime.
        """
        parser.add_argument(
            "--accept-eula",
            action="store_true",
            help=(
                "Accept the NVIDIA CloudXR EULA non-interactively "
                "(e.g. for CI or containers)."
            ),
        )

    @staticmethod
    def add_launch_wss_proxy_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--launch-wss-proxy`` on ``parser``.

        Uses :class:`argparse.BooleanOptionalAction`, so callers may pass
        ``--no-launch-wss-proxy`` when an external WSS proxy is already
        running or only the runtime subprocess is needed.
        """
        parser.add_argument(
            "--launch-wss-proxy",
            action=argparse.BooleanOptionalAction,
            default=True,
            help=(
                "Start the in-process WSS TLS proxy after the runtime is ready "
                "(default: true). Pass --no-launch-wss-proxy when an external proxy "
                "is already running or only the runtime subprocess is needed."
            ),
        )

    @staticmethod
    def add_launcher_arguments(parser: argparse.ArgumentParser) -> None:
        """Register CloudXR launcher CLI arguments on ``parser``."""
        CloudXRLauncher.add_cloudxr_install_dir_argument(parser)
        CloudXRLauncher.add_cloudxr_device_profile_argument(parser)
        CloudXRLauncher.add_cloudxr_env_config_argument(parser)
        CloudXRLauncher.add_accept_eula_argument(parser)
        CloudXRLauncher.add_launch_cloudxr_runtime_argument(parser)
        CloudXRLauncher.add_launch_wss_proxy_argument(parser)

    @staticmethod
    def _resolve_install_dir(
        args: argparse.Namespace,
        install_dir: str | None = None,
    ) -> str:
        """Return ``install_dir`` or ``args.cloudxr_install_dir`` when registered."""
        if install_dir is not None:
            return install_dir
        return getattr(args, "cloudxr_install_dir", "~/.cloudxr")

    @staticmethod
    def _resolve_device_profile(
        args: argparse.Namespace,
        device_profile: str | None = None,
    ) -> str:
        """Return ``device_profile`` or ``args.cloudxr_device_profile`` when registered."""
        if device_profile is not None:
            return device_profile
        return getattr(args, "cloudxr_device_profile", DEFAULT_DEVICE_PROFILE)

    @staticmethod
    def _resolve_env_config(
        args: argparse.Namespace,
        env_config: str | Path | None = None,
    ) -> str | Path | None:
        """Return ``env_config`` or ``args.cloudxr_env_config`` when registered."""
        if env_config is not None:
            return env_config
        return getattr(args, "cloudxr_env_config", None)

    @staticmethod
    def _resolve_accept_eula(
        args: argparse.Namespace,
        accept_eula: bool | None = None,
    ) -> bool:
        """Return ``accept_eula`` or ``args.accept_eula`` when registered.

        ``None`` means no override (fall back to ``args``); an explicit ``False``
        disables EULA acceptance even when ``args.accept_eula`` is true.
        """
        if accept_eula is not None:
            return accept_eula
        return bool(getattr(args, "accept_eula", False))

    @staticmethod
    def _resolve_start_wss_proxy(
        args: argparse.Namespace,
        start_wss_proxy: bool | None = None,
    ) -> bool:
        """Return ``start_wss_proxy`` or ``args.launch_wss_proxy`` when registered."""
        if start_wss_proxy is not None:
            return start_wss_proxy
        return bool(getattr(args, "launch_wss_proxy", True))

    @staticmethod
    def launch_context(
        args: argparse.Namespace,
        *,
        install_dir: str | None = None,
        env_config: str | Path | None = None,
        device_profile: str | None = None,
        accept_eula: bool | None = None,
        setup_oob: bool = False,
        usb_local: bool = False,
        host_client: bool = False,
        start_wss_proxy: bool | None = None,
    ) -> contextlib.AbstractContextManager[CloudXRLauncher | None]:
        """Start :class:`CloudXRLauncher` when ``args.launch_cloudxr_runtime`` is true.

        Returns :func:`contextlib.nullcontext` when ``args.launch_cloudxr_runtime`` is
        false so callers can always use ``with CloudXRLauncher.launch_context(args):``.

        ``install_dir``, ``env_config``, ``device_profile``, ``accept_eula``, and
        ``start_wss_proxy`` default to the values registered by
        :meth:`add_launcher_arguments` (``args.cloudxr_install_dir`` etc.); pass an
        explicit keyword only to override what came in on the command line. For
        ``accept_eula``, pass ``False`` to force-disable even when the CLI flag
        is set.
        """
        if not args.launch_cloudxr_runtime:
            return contextlib.nullcontext(None)
        return CloudXRLauncher(
            install_dir=CloudXRLauncher._resolve_install_dir(args, install_dir),
            env_config=CloudXRLauncher._resolve_env_config(args, env_config),
            device_profile=CloudXRLauncher._resolve_device_profile(
                args, device_profile
            ),
            accept_eula=CloudXRLauncher._resolve_accept_eula(args, accept_eula),
            setup_oob=setup_oob,
            usb_local=usb_local,
            host_client=host_client,
            start_wss_proxy=CloudXRLauncher._resolve_start_wss_proxy(
                args, start_wss_proxy
            ),
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> CloudXRLauncher:
        """Return the launcher for use in a ``with`` block."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop the launcher on exiting the ``with`` block."""
        self.stop()

    def stop(self) -> None:
        """Shut down the WSS proxy and terminate the runtime process.

        Safe to call multiple times or when nothing is running.

        Raises:
            RuntimeError: If the runtime process could not be terminated.
                The process handle is retained so callers can retry or
                inspect the still-running process.
        """
        self._stop_wss_proxy()

        if self._runtime_proc is not None:
            try:
                self._terminate_runtime()
            except RuntimeError:
                logger.warning(
                    "Failed to cleanly terminate CloudXR runtime process (pid=%s); "
                    "handle retained for later cleanup",
                    self._runtime_proc.pid,
                )
                raise
            self._runtime_proc = None
            logger.info("CloudXR runtime process stopped")

    def health_check(self) -> None:
        """Verify that the runtime process and WSS proxy are healthy.

        Returns immediately when the runtime is running and, when the WSS
        proxy was started, its background thread is alive.  Raises
        :class:`RuntimeError` with diagnostic details when any monitored
        component has stopped unexpectedly, allowing embedding applications
        to perform a controlled teardown.

        Raises:
            RuntimeError: If the launcher has not been started, or if
                the runtime process or (when enabled) the WSS proxy has stopped.
        """
        if self._runtime_proc is None:
            raise RuntimeError("CloudXR launcher is not running")

        exit_code = self._runtime_proc.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"CloudXR runtime process exited unexpectedly (exit code {exit_code})"
            )

        if (
            self._start_wss_proxy
            and self._wss_thread is not None
            and not self._wss_thread.is_alive()
        ):
            raise RuntimeError("CloudXR WSS proxy thread stopped unexpectedly")

    @property
    def wss_log_path(self) -> Path | None:
        """Path to the WSS proxy log file, or ``None`` if not yet started."""
        return self._wss_log_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_stale_runtime(env_cfg: EnvConfig) -> None:
        """Remove stale sentinel files from a previous runtime that wasn't cleaned up.

        If the ``ipc_cloudxr`` socket still exists in the run directory, a
        previous Monado/CloudXR process is likely still alive.  We send
        SIGTERM to the process group that owns the socket, giving it a
        chance to exit cleanly before we start a fresh runtime.
        """
        run_dir = env_cfg.openxr_run_dir()
        ipc_socket = os.path.join(run_dir, "ipc_cloudxr")

        if os.path.exists(ipc_socket):
            logger.warning(
                "Stale CloudXR IPC socket found at %s; attempting cleanup of previous runtime",
                ipc_socket,
            )
            try:
                result = subprocess.run(
                    ["fuser", "-k", "-TERM", ipc_socket],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    time.sleep(1)
                    logger.info("Sent SIGTERM to processes holding stale IPC socket")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

            try:
                os.remove(ipc_socket)
            except FileNotFoundError:
                pass

        for name in ("runtime_started", "monado.pid", "cloudxr.pid"):
            try:
                os.remove(os.path.join(run_dir, name))
            except FileNotFoundError:
                pass

    def _collect_startup_failure_detail(self, logs_dir: Path) -> str:
        """Build a diagnostic string after a failed runtime startup.

        Captures the process exit code, subprocess stderr pipe, the
        runtime stderr log file (written by :func:`~.runtime.run`), and
        the most recent CloudXR native server log.
        """
        _MAX_LOG_BYTES = 4096
        parts: list[str] = []
        proc = self._runtime_proc
        if proc is not None:
            exit_code = proc.poll()
            if exit_code is not None:
                parts.append(f"Process exited with code {exit_code}.")
                stderr_pipe = getattr(proc, "stderr", None)
                if stderr_pipe is not None:
                    try:
                        stderr_tail = stderr_pipe.read(_MAX_LOG_BYTES)
                        if stderr_tail:
                            parts.append(
                                f"stderr: {stderr_tail.decode(errors='replace').strip()}"
                            )
                    except Exception:
                        pass
            else:
                parts.append("Process is still running but did not signal readiness.")

        for log_path in self._gather_diagnostic_logs(logs_dir):
            try:
                content = log_path.read_text(errors="replace").strip()
                if not content:
                    continue
                if len(content) > _MAX_LOG_BYTES:
                    content = "...\n" + content[-_MAX_LOG_BYTES:]
                parts.append(f"{log_path.name}:\n{content}")
            except Exception:
                pass

        parts.append(f"Check logs under {logs_dir} for details.")
        return "  ".join(parts)

    @staticmethod
    def _gather_diagnostic_logs(logs_dir: Path) -> list[Path]:
        """Return log files useful for diagnosing a startup failure."""
        result: list[Path] = []

        stderr_log = logs_dir / "runtime_stderr.log"
        if stderr_log.is_file():
            result.append(stderr_log)

        cxr_logs = sorted(logs_dir.glob("cxr_server.*.log"))
        if cxr_logs:
            result.append(cxr_logs[-1])

        return result

    def _is_runtime_alive(self) -> bool:
        """Return whether the runtime subprocess is still running."""
        return self._runtime_proc is not None and self._runtime_proc.poll() is None

    def _terminate_runtime(self) -> None:
        """Terminate the runtime subprocess and all its children.

        On POSIX, the subprocess is launched with ``start_new_session=True``
        so it leads its own process group; ``killpg`` tears down Monado and
        other children.  Windows is not supported (see
        :meth:`_terminate_runtime_windows`).
        """
        proc = self._runtime_proc
        if proc is None or proc.poll() is not None:
            return

        if sys.platform == "win32":
            self._terminate_runtime_windows(proc)
            return

        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            return

        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=RUNTIME_TERMINATE_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass

        if proc.poll() is None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                return
            try:
                proc.wait(timeout=RUNTIME_TERMINATE_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                pass

        if proc.poll() is None:
            raise RuntimeError("Failed to terminate or kill runtime process group")

    @staticmethod
    def _terminate_runtime_windows(_proc: subprocess.Popen) -> None:
        """Windows runtime termination is not supported."""
        raise RuntimeError(
            "CloudXR runtime process termination is not supported on Windows"
        )

    # ------------------------------------------------------------------
    # WSS proxy (background thread with its own event loop)
    # ------------------------------------------------------------------

    def _start_wss_proxy_thread(self, log_path: Path) -> None:
        """Launch the WSS proxy in a daemon thread."""
        from .wss import run as wss_run

        loop = asyncio.new_event_loop()
        self._wss_loop = loop
        stop_future = loop.create_future()
        self._wss_stop_future = stop_future

        setup_oob = self._setup_oob
        usb_local = self._usb_local
        host_client = self._host_client

        def _run_wss() -> None:
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    wss_run(
                        log_file_path=log_path,
                        stop_future=stop_future,
                        setup_oob=setup_oob,
                        usb_local=usb_local,
                        host_client=host_client,
                    )
                )
            except Exception:
                logger.exception("WSS proxy thread exited with error")
            finally:
                loop.close()

        self._wss_thread = threading.Thread(
            target=_run_wss, name="cloudxr-wss-proxy", daemon=True
        )
        self._wss_thread.start()

    def _stop_wss_proxy(self) -> None:
        """Signal the WSS proxy to shut down and wait for the thread."""
        if self._wss_loop is not None and self._wss_stop_future is not None:
            loop = self._wss_loop
            future = self._wss_stop_future

            def _set_result() -> None:
                if not future.done():
                    future.set_result(None)

            if not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(_set_result)
                except RuntimeError:
                    logger.debug(
                        "WSS event loop closed before stop signal; "
                        "proxy already shut down"
                    )

        if self._wss_thread is not None:
            self._wss_thread.join(timeout=5)
            if self._wss_thread.is_alive():
                logger.warning("WSS proxy thread did not exit cleanly")

        self._wss_thread = None
        self._wss_loop = None
        self._wss_stop_future = None
