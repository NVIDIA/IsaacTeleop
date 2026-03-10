# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import asyncio
import ctypes
import multiprocessing
import os
import shutil
import signal
import sys
import threading

from .env_config import get_env_config


_EULA_URL = (
    "https://github.com/NVIDIA/IsaacTeleop/blob/main/deps/cloudxr/CLOUDXR_LICENSE"
)
_RUNTIME_JOIN_TIMEOUT = 10
_RUNTIME_STARTUP_TIMEOUT_SEC = 10


def check_eula() -> None:
    """Require CloudXR EULA to be accepted; exits the process if not. Call from main process before spawning runtime."""
    marker = os.path.join(get_env_config().openxr_run_dir(), "eula_accepted")
    if os.path.isfile(marker):
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

    run_dir = os.path.dirname(marker)
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    with open(marker, "w") as f:
        f.write("accepted\n")


def _get_sdk_path() -> str | None:
    """Return the path to the bundled CloudXR native libs (wheel package data), or None."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    native_dir = os.path.join(this_dir, "native")

    if not os.path.isfile(os.path.join(native_dir, "libcloudxr.so")):
        raise RuntimeError(f"CloudXR SDK missing libcloudxr.so at {native_dir}. ")

    return native_dir


async def wait_for_runtime_ready(
    process: multiprocessing.Process,
    timeout_sec: float = _RUNTIME_STARTUP_TIMEOUT_SEC,
) -> bool:
    """
    Return True when runtime is ready (lock file runtime_started). Return False on timeout or if
    the process exits early.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_sec

    lock_file = os.path.join(get_env_config().openxr_run_dir(), "runtime_started")

    while loop.time() < deadline:
        if not process.is_alive():
            return False

        if os.path.isfile(lock_file):
            return True

        await asyncio.sleep(1)

    # Runtime startup timeout reached, assume the runtime is not ready
    return False


def terminate_or_kill_runtime(process: multiprocessing.Process) -> None:
    """Terminate or kill the runtime process."""
    if process.is_alive():
        process.terminate()
        process.join(timeout=_RUNTIME_JOIN_TIMEOUT)
    if process.is_alive():
        process.kill()
        process.join(timeout=_RUNTIME_JOIN_TIMEOUT)
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

    for stale in ("ipc_cloudxr", "runtime_started"):
        p = os.path.join(run_dir, stale)
        if os.path.exists(p):
            os.remove(p)

    return openxr_dir


def run() -> None:
    """Run the CloudXR runtime service until SIGINT/SIGTERM. Blocks until shutdown."""
    cfg = get_env_config()
    sdk_path = _get_sdk_path()
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

    lib_path = os.path.join(sdk_path, "libcloudxr.so")
    lib = ctypes.CDLL(lib_path)
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
