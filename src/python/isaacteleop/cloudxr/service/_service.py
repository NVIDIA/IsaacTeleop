# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Owner of the CloudXR runtime process and the WSS TLS proxy."""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..env_config import DEFAULT_DEVICE_PROFILE, ENV_FILE_NAME, EnvConfig
from ..runtime import (
    RUNTIME_STARTUP_TIMEOUT_SEC,
    RUNTIME_TERMINATE_TIMEOUT_SEC,
    get_sdk_path,
    is_runtime_live,
    resolve_cloudxr_runtime_module,
    check_eula,
    wait_for_runtime_ready_sync,
)

logger = logging.getLogger(__name__)

_RUNTIME_WORKER_CODE = """\
import sys, os
sys.path = [p for p in sys.path if p]
from {runtime_mod}.runtime import run
run()
"""


class CloudXRService:
    """Owns a CloudXR runtime process and its WSS TLS proxy.

    Both start on construction; use :meth:`stop` or the context manager
    protocol to shut them down.  The runtime runs as an isolated subprocess
    to avoid CUDA context conflicts with host applications like Isaac Sim
    that have already initialized GPU resources.

    Example::

        with CloudXRService() as service:
            # runtime + WSS proxy are running and owned by this process
            ...
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
    ) -> None:
        """Start the CloudXR runtime and the WSS proxy.

        Configures the environment, spawns the runtime subprocess, and starts
        the WSS TLS proxy.  Blocks until the runtime signals readiness (up to
        :data:`~isaacteleop.cloudxr.runtime.RUNTIME_STARTUP_TIMEOUT_SEC`)
        or raises :class:`RuntimeError` on failure.

        Args:
            install_dir: CloudXR install directory.
            env_config: Optional path to a KEY=value env file for
                CloudXR env-var overrides.
            device_profile: CloudXR ``NV_DEVICE_PROFILE`` when not set in
                *env_config* or the process environment.
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

        Raises:
            RuntimeError: If the EULA is not accepted, another runtime is
                already serving *install_dir*, or the runtime fails to
                start within the timeout.
        """
        self._install_dir = install_dir
        self._env_config = str(env_config) if env_config is not None else None
        self._device_profile = device_profile
        self._accept_eula = accept_eula
        self._setup_oob = setup_oob
        self._usb_local = usb_local
        self._host_client = host_client

        if self._usb_local or self._host_client:
            from ..oob_teleop_env import require_web_client_static_dir  # noqa: PLC0415

            require_web_client_static_dir()

        self._runtime_proc: subprocess.Popen | None = None
        self._wss_thread: threading.Thread | None = None
        self._wss_loop: asyncio.AbstractEventLoop | None = None
        self._wss_stop_future: asyncio.Future | None = None
        self._wss_log_path: Path | None = None
        self._atexit_registered = False
        self._stopping = False
        # sig -> (previous handler, service-installed wrapper)
        self._prev_signal_handlers: dict[int, tuple[object, object]] = {}

        # Before EnvConfig: resolving rewrites cloudxr.env and mutates
        # os.environ, which must not happen when the start is about to be
        # refused because another runtime owns this directory.
        run_dir = os.path.join(
            os.path.abspath(os.path.expanduser(self._install_dir)), "run"
        )
        self._cleanup_stale_runtime(run_dir)

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

        if not self._atexit_registered:
            atexit.register(self.stop)
            self._atexit_registered = True
        # SIGTERM/SIGINT do not run atexit; stop the session-scoped runtime first.
        self._install_signal_handlers()

        if not wait_for_runtime_ready_sync(is_process_alive=self._is_runtime_alive):
            detail = self._collect_startup_failure_detail(logs_dir_path)
            self.stop()
            raise RuntimeError(
                "CloudXR runtime failed to start within "
                f"{RUNTIME_STARTUP_TIMEOUT_SEC}s.  {detail}"
            )
        logger.info("CloudXR runtime ready")

        wss_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        wss_log_path = logs_dir_path / f"wss.{wss_ts}.log"
        self._wss_log_path = wss_log_path
        self._start_wss_proxy_thread(wss_log_path)
        logger.info("CloudXR WSS proxy started (log=%s)", wss_log_path)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> CloudXRService:
        """Return the service for use in a ``with`` block."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop the service on exiting the ``with`` block."""
        self.stop()

    def stop(self) -> None:
        """Shut down the WSS proxy and terminate the runtime process.

        Safe to call multiple times or when nothing is running.

        Raises:
            RuntimeError: If the runtime process could not be terminated.
                The process handle is retained so callers can retry or
                inspect the still-running process.
        """
        # Restore handlers only after teardown; _stopping blocks re-entrant stop().
        if self._stopping:
            return
        self._stopping = True
        try:
            self._stop_wss_proxy()

            if self._runtime_proc is not None:
                try:
                    self._terminate_runtime()
                except RuntimeError:
                    logger.warning(
                        "Failed to cleanly terminate CloudXR runtime process "
                        "(pid=%s); handle retained for later cleanup",
                        self._runtime_proc.pid,
                    )
                    raise
                self._runtime_proc = None
                logger.info("CloudXR runtime process stopped")
        finally:
            self._restore_signal_handlers()
            self._stopping = False

    def health_check(self) -> None:
        """Verify that the runtime process and WSS proxy are healthy.

        Returns immediately when the runtime is running and the WSS proxy
        thread, once started, is alive.  Raises :class:`RuntimeError` with
        diagnostic details when any monitored component has stopped
        unexpectedly, allowing supervisors to perform a controlled teardown.

        Raises:
            RuntimeError: If the service has not been started, or if
                the runtime process or the WSS proxy has stopped.
        """
        if self._runtime_proc is None:
            raise RuntimeError("CloudXR service is not running")

        exit_code = self._runtime_proc.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"CloudXR runtime process exited unexpectedly (exit code {exit_code})"
            )

        if self._wss_thread is not None and not self._wss_thread.is_alive():
            raise RuntimeError("CloudXR WSS proxy thread stopped unexpectedly")

    @property
    def wss_log_path(self) -> Path | None:
        """Path to the WSS proxy log file, or ``None`` if not yet started."""
        return self._wss_log_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers that call :meth:`stop`, then the prior handler."""
        if threading.current_thread() is not threading.main_thread():
            return

        self._restore_signal_handlers()

        def _make_handler(prev):
            def _handler(signum, frame):
                try:
                    self.stop()
                finally:
                    if callable(prev):
                        prev(signum, frame)
                    else:
                        signal.signal(signum, prev)
                        if prev == signal.SIG_DFL:
                            os.kill(os.getpid(), signum)

            return _handler

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                prev = signal.getsignal(sig)
                handler = _make_handler(prev)
                signal.signal(sig, handler)
            except (ValueError, OSError):
                continue
            self._prev_signal_handlers[sig] = (prev, handler)

    def _restore_signal_handlers(self) -> None:
        """Restore handlers from :meth:`_install_signal_handlers` if still ours.

        Skip overwrite when a host replaced the wrapper. Keep the entry if
        restore fails (e.g. non-main thread) for a later attempt.
        """
        for sig in list(self._prev_signal_handlers):
            prev, ours = self._prev_signal_handlers[sig]
            try:
                if signal.getsignal(sig) is not ours:
                    del self._prev_signal_handlers[sig]
                    continue
                signal.signal(sig, prev)
            except (ValueError, OSError):
                continue
            del self._prev_signal_handlers[sig]

    @staticmethod
    def _cleanup_stale_runtime(run_dir: str) -> None:
        """Refuse to start over a live runtime; otherwise clear stale sentinels.

        A run directory holds one runtime.  Liveness is decided by
        connecting to the IPC socket, not by its existence — the file
        routinely outlives the process that made it.

        Runs before :class:`EnvConfig` resolves anything: resolving rewrites
        ``cloudxr.env`` in place, so a refused start would otherwise have
        already replaced the live runtime's environment with its own.

        Raises:
            RuntimeError: If a runtime is already serving the run directory.
        """
        if is_runtime_live(run_dir):
            raise RuntimeError(
                f"A CloudXR runtime is already serving {run_dir}; starting a "
                "second one would drop the live session.  To use the running "
                f"runtime: source {os.path.join(run_dir, ENV_FILE_NAME)} — "
                "applications that embed CloudXRLauncher attach to it on their "
                "own.  To replace it: python -m isaacteleop.cloudxr.service "
                "stop (Ctrl+C in its terminal if it is running in the "
                "foreground)."
            )

        for name in ("ipc_cloudxr", "runtime_started", "monado.pid", "cloudxr.pid"):
            path = os.path.join(run_dir, name)
            try:
                os.remove(path)
            except FileNotFoundError:
                continue
            logger.warning("Removed stale CloudXR runtime file \033[90m%s\033[0m", path)

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
        from ..wss import run as wss_run  # noqa: PLC0415

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
