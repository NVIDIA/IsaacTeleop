# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import ctypes
import os
import shutil
import signal
import sys
import threading


_EULA_URL = (
    "https://github.com/NVIDIA/IsaacTeleop/blob/main/deps/cloudxr/CLOUDXR_LICENSE"
)
_EULA_MARKER = "eula_accepted"


def _eula_marker_path() -> str | None:
    """Path to persisted EULA marker file (~/.cloudxr/run/eula_accepted), or None if HOME unset."""
    return os.path.join(openxr_run_dir(), _EULA_MARKER)


def _eula_read_persisted() -> bool:
    path = _eula_marker_path()
    return path is not None and os.path.isfile(path)


def _eula_write_persisted() -> None:
    path = _eula_marker_path()
    run_dir = os.path.dirname(path)
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    with open(path, "w") as f:
        f.write("accepted\n")


def _require_eula() -> None:
    if _eula_read_persisted():
        return

    print(
        "\nNVIDIA CloudXR EULA must be accepted to run. View: " + _EULA_URL,
        file=sys.stderr,
    )
    try:
        reply = input("\nAccept NVIDIA CloudXR EULA? [y/N]: ").strip().lower()
    except EOFError:
        reply = ""
    if reply in ("y", "yes"):
        _eula_write_persisted()
        return
    print("EULA not accepted. Exiting.", file=sys.stderr)
    sys.exit(1)


def _sdk_path() -> str | None:
    """Return the path to the bundled CloudXR native libs (wheel package data), or None."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    native_dir = os.path.join(this_dir, "native")
    if os.path.isfile(os.path.join(native_dir, "libcloudxr.so")):
        return native_dir
    return None


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


def openxr_run_dir() -> str:
    if os.environ.get("HOME"):
        return os.path.abspath(os.path.join(os.environ["HOME"], ".cloudxr", "run"))
    raise RuntimeError("Failed to determine openxr run dir")


def run() -> None:
    """Run the CloudXR runtime service until SIGINT/SIGTERM. Blocks until shutdown."""
    _require_eula()
    sdk_path = _sdk_path()
    run_dir = openxr_run_dir()
    openxr_dir = _setup_openxr_dir(sdk_path, run_dir)

    json_path = os.path.join(openxr_dir, "openxr_cloudxr.json")
    os.environ["XR_RUNTIME_JSON"] = json_path
    os.environ["NV_CXR_RUNTIME_DIR"] = run_dir

    os.environ["NV_CXR_ENABLE_PUSH_DEVICES"] = "true"
    os.environ["NV_CXR_ENABLE_TENSOR_DATA"] = "true"
    os.environ["XRT_NO_STDIN"] = "true"
    os.environ["NV_CXR_FILE_LOGGING"] = "false"
    os.environ["NV_DEVICE_PROFILE"] = "Quest3"

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
        print("Stopping CloudXR runtime...")
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
