# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Programmatic launcher for the CloudXR runtime and WSS proxy.

Wraps the logic from ``python -m isaacteleop.cloudxr`` into a reusable
start/stop API that can be called from embedding applications (e.g.
Isaac Lab Teleop) without requiring a separate terminal.
"""

from __future__ import annotations

import asyncio
import atexit
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
    check_eula,
    wait_for_runtime_ready_sync,
)

logger = logging.getLogger(__name__)

_RUNTIME_WORKER_CODE = """\
import sys, os
sys.path = [p for p in sys.path if p]
from isaacteleop.cloudxr.runtime import run
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
        accept_eula: bool = False,
    ) -> None:
        """Launch the CloudXR runtime and WSS proxy.

        Configures the environment, spawns the runtime subprocess, and
        starts the WSS TLS proxy.  Blocks until the runtime signals
        readiness (up to
        :data:`~isaacteleop.cloudxr.runtime.RUNTIME_STARTUP_TIMEOUT_SEC`)
        or raises :class:`RuntimeError` on failure.

        Args:
            install_dir: CloudXR install directory.
            env_config: Optional path to a KEY=value env file for
                CloudXR env-var overrides.
            accept_eula: Accept the NVIDIA CloudXR EULA
                non-interactively.  When ``False`` and the EULA marker
                does not exist, the user is prompted on stdin.

        Raises:
            RuntimeError: If the EULA is not accepted or the runtime
                fails to start within the timeout.
        """
        self._install_dir = install_dir
        self._env_config = str(env_config) if env_config is not None else None
        self._accept_eula = accept_eula

        self._runtime_proc: subprocess.Popen | None = None
        self._wss_thread: threading.Thread | None = None
        self._wss_loop: asyncio.AbstractEventLoop | None = None
        self._wss_stop_future: asyncio.Future | None = None
        self._wss_log_path: Path | None = None
        self._atexit_registered = False

        env_cfg = EnvConfig.from_args(self._install_dir, self._env_config)
        try:
            check_eula(accept_eula=self._accept_eula or None)
        except SystemExit as exc:
            raise RuntimeError(
                "CloudXR EULA was not accepted; cannot start the runtime"
            ) from exc
        logs_dir_path = env_cfg.ensure_logs_dir()

        self._cleanup_stale_runtime(env_cfg)

        self._runtime_proc = subprocess.Popen(
            [sys.executable, "-c", _RUNTIME_WORKER_CODE],
            env=os.environ.copy(),
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

        wss_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        wss_log_path = logs_dir_path / f"wss.{wss_ts}.log"
        self._wss_log_path = wss_log_path
        self._start_wss_proxy(wss_log_path)
        logger.info("CloudXR WSS proxy started (log=%s)", wss_log_path)

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

        Returns immediately when both components are running.  Raises
        :class:`RuntimeError` with diagnostic details when any component
        has stopped unexpectedly, allowing embedding applications to
        perform a controlled teardown.

        Raises:
            RuntimeError: If the launcher has not been started, or if
                the runtime process or WSS proxy has stopped.
        """
        if self._runtime_proc is None:
            raise RuntimeError("CloudXR launcher is not running")

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

        started = os.path.join(run_dir, "runtime_started")
        try:
            os.remove(started)
        except FileNotFoundError:
            pass

    def _collect_startup_failure_detail(self, logs_dir: Path) -> str:
        """Build a diagnostic string after a failed runtime startup."""
        parts: list[str] = []
        proc = self._runtime_proc
        if proc is not None:
            exit_code = proc.poll()
            if exit_code is not None:
                parts.append(f"Process exited with code {exit_code}.")
                stderr_pipe = getattr(proc, "stderr", None)
                if stderr_pipe is not None:
                    try:
                        stderr_tail = stderr_pipe.read(4096)
                        if stderr_tail:
                            parts.append(
                                f"stderr: {stderr_tail.decode(errors='replace').strip()}"
                            )
                    except Exception:
                        pass
            else:
                parts.append("Process is still running but did not signal readiness.")

        parts.append(f"Check logs under {logs_dir} for details.")
        return "  ".join(parts)

    def _is_runtime_alive(self) -> bool:
        """Return whether the runtime subprocess is still running."""
        return self._runtime_proc is not None and self._runtime_proc.poll() is None

    def _terminate_runtime(self) -> None:
        """Terminate the runtime subprocess and all its children.

        Because the subprocess is launched with ``start_new_session=True``
        it is the leader of its own process group.  Sending the signal to
        the negative PID kills the entire group (including Monado and any
        other children), preventing stale processes from lingering.
        """
        proc = self._runtime_proc
        if proc is None or proc.poll() is not None:
            return

        pgid = os.getpgid(proc.pid)

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

    # ------------------------------------------------------------------
    # WSS proxy (background thread with its own event loop)
    # ------------------------------------------------------------------

    def _start_wss_proxy(self, log_path: Path) -> None:
        """Launch the WSS proxy in a daemon thread."""
        from .wss import run as wss_run

        loop = asyncio.new_event_loop()
        self._wss_loop = loop
        stop_future = loop.create_future()
        self._wss_stop_future = stop_future

        def _run_wss() -> None:
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    wss_run(log_file_path=log_path, stop_future=stop_future)
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
