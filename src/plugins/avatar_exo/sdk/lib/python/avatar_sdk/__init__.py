"""avatar_sdk package __init__.py for deb / distribution installs.

Preloads libavatar_sdk.so (packed C++ DSO) with RTLD_GLOBAL, then imports the
pybind extension from the same package directory (avatar_sdk.cpython-3XX-*.so).
CasADi nlpsol plugins are loaded later by CasADi itself; do not preload
libcasadi.so here because the package may also carry a dynamic CasADi with a
different C++ ABI than the static CasADi symbols inside libavatar_sdk.so.

Expected layout (dist or deb):
  <python_root>/
    avatar_sdk/
      __init__.py       <-- this file
      avatar_pb2_loader.py
      avatar_sdk.cpython-310-x86_64-linux-gnu.so
      avatar_sdk.cpython-311-x86_64-linux-gnu.so
      ...

  ../../ or /opt/avatar-sdk/lib/
    libavatar_sdk.so
"""

import ctypes
import os

_pkg_dir = os.path.dirname(os.path.abspath(__file__))
_python_root = os.path.dirname(_pkg_dir)

_lib_candidates = [
    os.path.join(os.path.dirname(_python_root), "lib"),   # dist/linux/lib/
    os.path.dirname(_python_root),                          # deb layout: libavatar_sdk.so beside python/
    "/opt/avatar-sdk/lib",                                  # deb install
    "/usr/lib/avatar-sdk",                                  # legacy deb install
    _python_root,                                           # fallback
]

_lib_loaded = False
for _lib_dir in _lib_candidates:
    for _dep_name in (
        "libgomp.so.1",
        "libgfortran.so.5",
        "libcasadi-tp-openblas.so.0",
        "libcoinmetis.so.2",
        "libcoinmumps.so.3",
        "libipopt.so.3",
        "libsipopt.so.3",
    ):
        _dep_path = os.path.join(_lib_dir, _dep_name)
        if os.path.exists(_dep_path):
            try:
                ctypes.CDLL(_dep_path, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass
    for _lib_name in ("libavatar_sdk.so", "libavatar.so", "libavatar_sdk_wrapper.so"):
        _lib_path = os.path.join(_lib_dir, _lib_name)
        if os.path.exists(_lib_path):
            try:
                ctypes.CDLL(_lib_path, mode=ctypes.RTLD_GLOBAL)
                _lib_loaded = True
                break
            except OSError:
                pass
    if _lib_loaded:
        break

if not _lib_loaded:
    import warnings

    warnings.warn(
        "libavatar_sdk.so (or legacy libavatar.so / libavatar_sdk_wrapper.so) not found. "
        "Set LD_LIBRARY_PATH or install the avatar-sdk deb.",
        RuntimeWarning,
        stacklevel=2,
    )

from .avatar_sdk import (
    AvatarSDK,
    AvatarDevice,
    setup_cpp_logging,
    DeviceSide,
    DeviceType,
    UsbConnectionState,
    ErrorCode,
    DeviceDataCategery,
    Stamp,
    Header,
    Joint,
    Point,
    Quaternion,
    Vector3,
    Pose,
    Hand,
    HandSkeleton,
    AvatarDataFrame,
    PayloadCase,
    DeviceInfo,
    AVATAR_SDK_VERSION,
)

from . import avatar_pb2_loader as avatar_pb2  # noqa: F401

__version__ = AVATAR_SDK_VERSION
__all__ = [
    "AvatarSDK",
    "AvatarDevice",
    "setup_cpp_logging",
    "DeviceSide",
    "DeviceType",
    "UsbConnectionState",
    "ErrorCode",
    "DeviceDataCategery",
    "DeviceInfo",
    "AVATAR_SDK_VERSION",
    "Stamp",
    "Header",
    "Joint",
    "Point",
    "Quaternion",
    "Vector3",
    "Pose",
    "Hand",
    "HandSkeleton",
    "AvatarDataFrame",
    "PayloadCase",
    "avatar_pb2",
]
