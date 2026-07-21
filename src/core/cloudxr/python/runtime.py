# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import asyncio
import ctypes
import glob
import importlib
import importlib.util
import multiprocessing
import os
import shutil
import signal
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .env_config import get_env_config


_EULA_URL = (
    "https://github.com/NVIDIA/IsaacTeleop/blob/main/deps/cloudxr/CLOUDXR_LICENSE"
)

RUNTIME_STARTUP_TIMEOUT_SEC: float = 30
"""Maximum time [s] to wait for the runtime ``runtime_started`` sentinel."""

RUNTIME_TERMINATE_TIMEOUT_SEC: float = 10
"""Timeout [s] for each escalation step (SIGTERM, then SIGKILL) when stopping the runtime."""

RUNTIME_POLL_INTERVAL_SEC: float = 0.5
"""Polling interval [s] used by :func:`wait_for_runtime_ready_sync`."""

_CLOUDXR_EXP_ENV = "ISAAC_TELEOP_CLOUDXR_EXP"
_CLOUDXR_JOIN_MAIN_ENV = "ISAAC_TELEOP_CLOUDXR_JOIN_MAIN"
_CLOUDXR_MODULE = "isaacteleop.cloudxr"
_CLOUDXR_EXP_MODULE = "isaacteleop.cloudxr_exp"


def _is_tegra_t234() -> bool:
    """Return True on Jetson Orin-class platforms (T234 / CHIPID 0x23)."""
    boot = Path("/etc/nv_boot_control.conf")
    if boot.is_file():
        try:
            text = boot.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        for line in text.splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "TEGRA_CHIPID" and value.strip() == "0x23":
                return True

    compatible = Path("/proc/device-tree/compatible")
    if compatible.is_file():
        try:
            data = compatible.read_bytes().decode("utf-8", errors="ignore")
        except OSError:
            data = ""
        if "tegra234" in data:
            return True
    return False


def _should_use_exp() -> bool:
    """Return True when the experimental CloudXR runtime should be used."""
    raw = os.environ.get(_CLOUDXR_EXP_ENV, "").strip().lower()
    if not raw:
        return _is_tegra_t234()
    return raw in ("1", "true", "yes", "on")


def _should_join_main() -> bool:
    """Return True when ``nv_cxr_service_join`` should run on the main thread."""
    raw = os.environ.get(_CLOUDXR_JOIN_MAIN_ENV, "").strip().lower()
    if not raw:
        return _is_tegra_t234()
    return raw in ("1", "true", "yes", "on")


def _is_exp_available() -> bool:
    try:
        return importlib.util.find_spec(f"{_CLOUDXR_EXP_MODULE}.runtime") is not None
    except ModuleNotFoundError:
        return False


def resolve_cloudxr_runtime_module() -> str:
    """Return the module prefix whose ``runtime.run`` should be spawned."""
    if _should_use_exp():
        if not _is_exp_available():
            raise RuntimeError(
                f"Experimental CloudXR runtime package {_CLOUDXR_EXP_MODULE} is not installed. "
                f"Rebuild with -DENABLE_CLOUDXR_EXP_BUNDLE=ON to include it, "
                f"or set {_CLOUDXR_EXP_ENV}=0 to force the stable runtime."
            )
        return _CLOUDXR_EXP_MODULE
    return _CLOUDXR_MODULE


def get_sdk_path() -> str:
    """Return ``native/`` for the resolved stable or experimental runtime package."""
    mod = resolve_cloudxr_runtime_module()
    pkg = importlib.import_module(mod)
    sdk_dir = os.path.join(os.path.dirname(os.path.abspath(pkg.__file__)), "native")
    if not os.path.isfile(os.path.join(sdk_dir, "libcloudxr.so")):
        raise RuntimeError(f"CloudXR SDK missing libcloudxr.so at {sdk_dir}.")
    return sdk_dir


def _write_eula_marker(marker: str) -> None:
    run_dir = os.path.dirname(marker)
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    with open(marker, "w") as f:
        f.write("accepted\n")


def check_eula(*, accept_eula: bool | None = None) -> None:
    """Require CloudXR EULA to be accepted; exits the process if not. Call from main process before spawning runtime.

    Args:
        accept_eula: If True, accept and write marker. If None, check marker then prompt interactively.
    """
    marker = os.path.join(get_env_config().openxr_run_dir(), "eula_accepted")
    if os.path.isfile(marker):
        return

    if accept_eula is True:
        _write_eula_marker(marker)
        return

    print(
        "\nNVIDIA CloudXR EULA must be accepted to run. View: " + _EULA_URL,
        file=sys.stderr,
    )
    try:
        reply = input("\nAccept NVIDIA CloudXR EULA? [y/N]: ").strip().lower()
    except EOFError:
        reply = ""
    if reply not in ("y", "yes"):
        print("EULA not accepted. Exiting.", file=sys.stderr)
        sys.exit(1)

    _write_eula_marker(marker)


async def wait_for_runtime_ready(
    is_process_alive: Callable[[], bool],
    timeout_sec: float = RUNTIME_STARTUP_TIMEOUT_SEC,
    poll_interval_sec: float = RUNTIME_POLL_INTERVAL_SEC,
) -> bool:
    """Poll for the ``runtime_started`` sentinel file.

    This is the canonical implementation used by both the async callers
    and :func:`wait_for_runtime_ready_sync`.

    Args:
        is_process_alive: Callable returning ``True`` while the
            runtime process is still running.
        timeout_sec: Maximum time to wait [s].
        poll_interval_sec: Polling interval [s].

    Returns:
        ``True`` when the runtime is ready, ``False`` on timeout or
        if the process exits early.
    """
    lock_file = os.path.join(get_env_config().openxr_run_dir(), "runtime_started")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_sec

    while loop.time() < deadline:
        if not is_process_alive():
            return False
        if os.path.isfile(lock_file):
            return True
        await asyncio.sleep(poll_interval_sec)

    return False


def wait_for_runtime_ready_sync(
    is_process_alive: Callable[[], bool],
    timeout_sec: float = RUNTIME_STARTUP_TIMEOUT_SEC,
    poll_interval_sec: float = RUNTIME_POLL_INTERVAL_SEC,
) -> bool:
    """Synchronous poll for the ``runtime_started`` sentinel file.

    Unlike :func:`wait_for_runtime_ready`, this implementation uses
    :func:`time.monotonic` and :func:`time.sleep` so it is safe to call
    from threads or processes that already have a running asyncio event
    loop (e.g. Omniverse Kit / Isaac Sim).

    Args:
        is_process_alive: Callable returning ``True`` while the
            runtime process is still running.
        timeout_sec: Maximum time to wait [s].
        poll_interval_sec: Polling interval [s].

    Returns:
        ``True`` when the runtime is ready, ``False`` on timeout or
        if the process exits early.
    """
    lock_file = os.path.join(get_env_config().openxr_run_dir(), "runtime_started")
    deadline = time.monotonic() + timeout_sec

    while time.monotonic() < deadline:
        if not is_process_alive():
            return False
        if os.path.isfile(lock_file):
            return True
        time.sleep(poll_interval_sec)

    return False


def _load_libcloudxr(sdk_path: str) -> ctypes.CDLL:
    """Load libcloudxr.so with RTLD_DEEPBIND so the native stack resolves symbols from its own packaged libraries."""
    deepbind = getattr(os, "RTLD_DEEPBIND", 0)
    return ctypes.CDLL(os.path.join(sdk_path, "libcloudxr.so"), mode=deepbind)


def runtime_version() -> str:
    """Query the selected CloudXR runtime version (major.minor.patch)."""
    sdk_path = get_sdk_path()
    lib = _load_libcloudxr(sdk_path)
    if not hasattr(lib, "nv_cxr_get_runtime_version"):
        return "unknown"
    major, minor, patch = ctypes.c_uint32(), ctypes.c_uint32(), ctypes.c_uint32()
    lib.nv_cxr_get_runtime_version(
        ctypes.byref(major), ctypes.byref(minor), ctypes.byref(patch)
    )
    return f"{major.value}.{minor.value}.{patch.value}"


def latest_runtime_log() -> str | None:
    """Return the path to the most recent cxr_server log file, or None if not found."""
    logs_dir = get_env_config().ensure_logs_dir()
    candidates = sorted(glob.glob(str(logs_dir / "cxr_server.*.log")))
    return candidates[-1] if candidates else None


def terminate_or_kill_runtime(process: multiprocessing.Process) -> None:
    """Terminate or kill a :class:`multiprocessing.Process` runtime."""
    if process.is_alive():
        process.terminate()
        process.join(timeout=RUNTIME_TERMINATE_TIMEOUT_SEC)
    if process.is_alive():
        process.kill()
        process.join(timeout=RUNTIME_TERMINATE_TIMEOUT_SEC)
    if process.is_alive():
        raise RuntimeError("Failed to terminate or kill runtime process")


def _setup_openxr_dir(sdk_path: str, run_dir: str) -> str:
    """Create run dir and copy OpenXR runtime lib + json; return path to openxr dir (parent of run)."""
    openxr_dir = os.path.dirname(run_dir)
    os.makedirs(run_dir, mode=0o755, exist_ok=True)

    lib_src = os.path.join(sdk_path, "libopenxr_cloudxr.so")
    json_src = os.path.join(sdk_path, "openxr_cloudxr.json")
    for name, src in (
        ("libopenxr_cloudxr.so", lib_src),
        ("openxr_cloudxr.json", json_src),
    ):
        if not os.path.isfile(src):
            raise RuntimeError(f"CloudXR SDK missing {name} at {src}. ")
        shutil.copy2(src, os.path.join(openxr_dir, name))

    for stale in ("ipc_cloudxr", "runtime_started", "monado.pid", "cloudxr.pid"):
        p = os.path.join(run_dir, stale)
        if os.path.exists(p):
            os.remove(p)

    return openxr_dir


def run() -> None:
    """Run the CloudXR runtime service until SIGINT/SIGTERM. Blocks until shutdown."""
    cfg = get_env_config()
    sdk_path = get_sdk_path()
    run_dir = cfg.openxr_run_dir()
    openxr_dir = _setup_openxr_dir(sdk_path, run_dir)

    expected_json = os.path.join(openxr_dir, "openxr_cloudxr.json")
    for var, expected in (
        ("XR_RUNTIME_JSON", expected_json),
        ("NV_CXR_RUNTIME_DIR", run_dir),
    ):
        actual = os.environ.get(var)
        if actual is None:
            raise RuntimeError(
                f"{var} is not set. Source setup_cloudxr_env.sh before running."
            )
        if os.path.abspath(actual) != os.path.abspath(expected):
            raise RuntimeError(
                f"{var} mismatch: environment has {actual!r}, expected {expected!r}"
            )

    prev_ld = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = sdk_path + (f":{prev_ld}" if prev_ld else "")

    # When file-logging is active the native library writes detailed logs to
    # NV_CXR_OUTPUT_DIR.  Suppress the console banner on stdout but redirect
    # stderr to a file so that Vulkan-loader diagnostics, GPU-init errors,
    # and Python tracebacks are preserved for post-mortem analysis.
    _file_logging = os.environ.get("NV_CXR_FILE_LOGGING", "yes")
    if _file_logging and _file_logging.lower() not in (
        "false",
        "off",
        "no",
        "n",
        "f",
        "0",
    ):
        logs_dir = cfg.ensure_logs_dir()
        stderr_log = os.path.join(str(logs_dir), "runtime_stderr.log")
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        stderr_fd = os.open(stderr_log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        os.dup2(devnull_fd, sys.stdout.fileno())
        os.dup2(stderr_fd, sys.stderr.fileno())
        os.close(devnull_fd)
        os.close(stderr_fd)

    lib = _load_libcloudxr(sdk_path)
    svc = ctypes.c_void_p()
    # Signal handler must only call stop() after create() has run; avoid calling with null svc.
    state = {"service_created": False, "interrupted": False}

    def stop(sig: int, frame: object) -> None:
        if not state["service_created"]:
            return
        state["interrupted"] = sig == signal.SIGINT
        lib.nv_cxr_service_stop(svc)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    lib.nv_cxr_service_create(ctypes.byref(svc))
    state["service_created"] = True
    lib.nv_cxr_service_start(svc)

    if _should_join_main():
        # Main-thread join avoids a "Couldn't create autoTSSkey mapping" abort
        # (auto on Orin). Blocks Python signal delivery until join returns; the
        # launcher can still terminate this worker process.
        lib.nv_cxr_service_join(svc)
        lib.nv_cxr_service_destroy(svc)
    else:
        # Run the blocking join() in a worker thread so the main thread stays in Python
        # and can run the signal handler. Otherwise Ctrl+C is not processed while we're
        # inside the native nv_cxr_service_join() call.
        def join_then_destroy() -> None:
            lib.nv_cxr_service_join(svc)
            lib.nv_cxr_service_destroy(svc)

        worker = threading.Thread(target=join_then_destroy, daemon=False)
        worker.start()
        worker.join()

    if state["interrupted"]:
        raise KeyboardInterrupt()
