# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Controls for non-logger (raw descriptor) output, for use inside this tree.

Some diagnostics cannot be routed through a logger at all: the CloudXR/Monado
OpenXR runtime and the Manus SDK format their own lines and write them straight
to file descriptor 1 or 2, exporting no log hook and, in the OpenXR case, not
implementing ``XR_EXT_debug_utils``. The descriptor is the only seam.

isaacteleop keeps that output out of the terminal and in the session's log
without taking the host process's descriptors away from it. See
:mod:`._native_fd` for the mechanism and its limits.

Deliberately not re-exported from the package ``__init__``: the sites that need
these are all in this tree (``TeleopSession``, ``cloudxr.service``), and a name
in ``logging_config.__all__`` is an interface to keep. If a host application
ever needs one, raise it there then -- the reasoning is in ``AGENTS.md``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

from . import _console, _native_fd


@contextlib.contextmanager
def capture_native_output() -> Iterator[Path | None]:
    """Send raw fd 1 / fd 2 writes to the session's capture file for this block.

    ``TeleopSession`` already wraps this around the native calls isaacteleop
    makes itself -- OpenXR session creation, DeviceIO session creation, plugin
    launch and the matching teardown -- which is every site in this tree that
    needs it::

        with capture_native_output():
            vendor_sdk.initialise()

    Yields the capture file's path, or ``None`` when nothing is captured
    (``ISAACTELEOP_NATIVE_CAPTURE=off``, or no writable log directory).

    Outside such a block isaacteleop does not touch fd 1 or fd 2 at all. Inside
    one it does, for the whole process -- a descriptor has no narrower scope --
    so raw writes by the host's other threads, and the stdio of a process the
    host spawns within the block, are captured too. Python-level writes
    (``print``, ``sys.stderr.write``) are not: the stream objects are moved onto
    duplicates of the real descriptors for the duration.
    """
    with _native_fd.scoped(_console.ensure_handler()) as path:
        yield Path(path) if path is not None else None


def native_capture_path() -> Path | None:
    """Where this process's captured non-logger output is persisted.

    ``<log_dir>/<YYYYmmdd-HHMMSS>.isaacteleop.<pid>.native.log``, with
    ``log_dir()`` resolving as documented there. ``None`` before anything has
    opened it, or if it could not be created. A file nothing ever wrote to is
    removed at exit.
    """
    path = _native_fd.capture_path()
    return Path(path) if path is not None else None


def native_capture_fd() -> int | None:
    """An open, append-mode descriptor on the capture file, for a child's stdio.

    Passed as ``stdout=``/``stderr=`` when this tree launches a process that
    loads non-logger native code (``cloudxr.service``'s runtime worker), so the
    child's output is persisted with the rest of the session instead of
    appearing on the host's terminal. A process isaacteleop launched is not the
    host, so pointing *its* descriptors at the capture file is exactly the move
    this design relies on.

    ``None`` when there is no capture file, in which case letting the child
    inherit is the right fallback. Never close it: it belongs to
    :mod:`isaacteleop.logging_config` for the life of the process.
    """
    return _native_fd.capture_fd()
