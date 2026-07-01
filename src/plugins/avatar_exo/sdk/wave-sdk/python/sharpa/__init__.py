"""Sharpa Wave SDK — multi-version native extension loader.

Layout (after deb install or dist/ staging):
    python/
      sharpa/
        __init__.py                              ← this file
        sharpa.cpython-310-x86_64-linux-gnu.so
        sharpa.cpython-311-x86_64-linux-gnu.so
        ...

Python's import system picks the .so whose cpython tag matches the
running interpreter, so a single install supports 3.10 – 3.13+.
"""

import sys
import os


def _try_preload_libpython():
    """Best-effort preload of libpythonX.Y.so from the active prefix.

    System-installed Pythons put this in a linker-visible path, but conda /
    venv environments often don't.  Pre-loading it with RTLD_GLOBAL makes
    the symbol table available to the pybind11 extension that follows.
    """
    import ctypes
    import ctypes.util

    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    if ctypes.util.find_library(f"python{ver}"):
        return  # already discoverable

    candidate = os.path.join(sys.prefix, "lib", f"libpython{ver}.so.1.0")
    if os.path.isfile(candidate):
        try:
            ctypes.CDLL(candidate, mode=ctypes.RTLD_GLOBAL)
        except OSError:
            pass


_try_preload_libpython()

try:
    from .sharpa import *  # noqa: F401,F403
except ImportError:
    _dir = os.path.dirname(os.path.abspath(__file__))
    _ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    _tag = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    _available = sorted(
        f for f in os.listdir(_dir)
        if f.startswith("sharpa.cpython") and f.endswith(".so")
    )

    if not any(_tag in f for f in _available):
        raise ImportError(
            f"No sharpa native extension for Python {_ver}.\n"
            f"Available: {_available}\n"
            f"Build/install the SDK for Python {_ver}, or switch to a "
            f"Python that matches one of the above."
        ) from None
    # The correct tag exists but the load still failed (missing .so dep, etc.)
    raise
