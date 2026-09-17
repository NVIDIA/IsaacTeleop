# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Host-facing controls for non-logger (raw descriptor) output.

Some diagnostics cannot be routed through a logger at all: the CloudXR/Monado
OpenXR runtime and the Manus SDK format their own lines and write them straight
to file descriptor 1 or 2, exporting no log hook and, in the OpenXR case, not
implementing ``XR_EXT_debug_utils``. The descriptor is the only seam.

isaacteleop keeps that output out of the terminal and in the session's log
without taking the host process's descriptors away from it. See
:mod:`._native_fd` for the mechanism and its limits.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

from . import _console, _native_fd


@contextlib.contextmanager
def capture_native_output() -> Iterator[Path | None]:
    """Send raw fd 1 / fd 2 writes to the session's capture file for this block.

    isaacteleop already wraps this around the native calls it makes itself --
    OpenXR session creation, DeviceIO session creation, plugin launch and the
    matching teardown -- so a host that only calls ``TeleopSession`` needs
    nothing. It is public for a host that loads more non-logger native code of
    its own and wants the same treatment::

        from isaacteleop import logging_config

        with logging_config.capture_native_output():
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


def native_capture_mode() -> str:
    """``"off"``, ``"scoped"`` or ``"process"``; see :func:`set_native_capture_mode`."""
    return _native_fd.mode()


def set_native_capture_mode(mode: str) -> None:
    """Choose how far isaacteleop may go in rebinding fd 1 and fd 2.

    ``"scoped"`` (the default)
        Only inside :func:`capture_native_output`. The host owns its
        descriptors everywhere else.
    ``"off"``
        Never in this process. Non-logger native output goes wherever the
        host's descriptors already point -- the terminal, normally -- and is
        not persisted. Processes isaacteleop launches itself still write to the
        capture file; their descriptors are not the host's.
    ``"process"``
        Rebound once, for the life of the process. This is what isaacteleop
        used to do unconditionally at import; it is now something a host has to
        ask for, because it also captures the host's own raw writes and every
        subprocess the host starts afterwards.

    Equivalent to the ``ISAACTELEOP_NATIVE_CAPTURE`` environment variable, which
    a host can set before ``import isaacteleop``; this call also exports it, so
    child processes inherit the choice.

    Raises:
        ValueError: if *mode* is not one of the three names above.
    """
    _native_fd.set_mode(mode)


def set_native_echo(enabled: bool | None) -> None:
    """Show captured non-logger output on the terminal as it arrives.

    Independent of whether it is persisted, which it always is. ``None``
    restores the default, which is to echo exactly when the console threshold is
    ``TRACE`` -- so ``set_console_level("trace")`` remains the one-knob way to
    watch vendor chatter live.
    """
    _native_fd.set_echo(enabled)
