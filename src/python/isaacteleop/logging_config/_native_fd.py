# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Capture of raw fd 1 / fd 2 writes that never reach the logger tree."""

from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
import time
from typing import TextIO

from ._core import TRACE, log_dir

_FD_LABELS = {1: "stdout", 2: "stderr"}

_saved: dict[int, TextIO] = {}
_pumps: dict[int, threading.Thread] = {}
_echo: dict[int, bool] = {}


def _write_all(fd: int, data: bytes) -> None:
    """``os.write`` until *data* is gone; a tty or a full disk can short-write."""
    while data:
        data = data[os.write(fd, data) :]


def _pump(fd: int, read_fd: int, sink_path: str) -> None:
    """Drain *fd*'s pipe into its capture file, mirroring it while echo is on.

    The file is opened on the first byte, not up front: most processes that
    import isaacteleop never emit raw fd 1/2 output at all, and creating the
    file eagerly left a pair of empty logs behind for every one of them.
    """
    sink_fd = -1
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as pipe:
            while chunk := pipe.read(65536):
                try:
                    if sink_fd < 0:
                        sink_fd = os.open(
                            sink_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644
                        )
                    _write_all(sink_fd, chunk)
                    saved = _saved.get(fd)
                    if _echo.get(fd) and saved is not None:
                        _write_all(saved.fileno(), chunk)
                except OSError:
                    pass  # keep draining regardless: see the finally below
    finally:
        if sink_fd >= 0:
            os.close(sink_fd)
        # Nothing else drains this pipe, so a writer would block for good once
        # it filled (64 KiB) -- the very failure cloudxr/service/_service.py
        # avoids by giving the runtime a file. Hand the fd back to the
        # terminal instead: losing the capture beats wedging the runtime.
        saved = _saved.get(fd)
        if saved is not None:
            os.dup2(saved.fileno(), fd)


def _reserve_std_fds() -> None:
    """Make sure fds 1 and 2 are open before any allocation below.

    os.open()/os.pipe() hand out the lowest free descriptor. If this process
    was started with stdout or stderr closed -- daemons do exactly that -- the
    capture file or the pipe lands *on* the number we are about to dup2() over,
    and the dup2 then silently repoints it: sink_fd stops referring to the file
    and becomes the pipe's own write end, so the pump reads a chunk and writes
    it straight back into the pipe it came from. Every captured byte is lost.
    Attaching /dev/null to a closed std fd first keeps every allocation clear of
    the two descriptors this module rebinds.
    """
    for std in (1, 2):
        try:
            os.fstat(std)
        except OSError:
            opened = os.open(os.devnull, os.O_WRONLY)
            if opened != std:
                os.dup2(opened, std)
                os.close(opened)


def _capture(fd: int, console_handler: logging.StreamHandler) -> None:
    """Point *fd* (1 or 2) at a pipe drained into its own file; idempotent.

    Native code -- the CloudXR/Monado OpenXR runtime above all -- writes its
    diagnostics straight to fd 1/2 and cannot be routed into this logger tree:
    it exports no log hook and does not implement ``XR_EXT_debug_utils``, so
    the descriptor is the only seam. What comes out is raw text rather than
    records, hence a separate file per fd from the handler-formatted one.

    ``sys.stdout``/``sys.stderr`` are moved onto a duplicate of the real
    descriptor instead of following it, so ``print()``, ``print(file=
    sys.stderr)``, and uncaught tracebacks all stay on the terminal --
    without this, ordinary ``print()`` calls (targeting fd 1 by default)
    would vanish into the capture pipe along with the native library's own
    fd 1 writes, since Python cannot tell the two apart at the fd level.
    Processes forked afterwards inherit the redirection; the C++ console
    sink writes through its own fd 1 handle taken before this runs, and
    the file rotation handler writes through a plain file object, so
    neither is affected by fd 1 being repointed here.
    """
    if fd in _saved:
        return
    _reserve_std_fds()
    label = _FD_LABELS[fd]
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    sink_path = str(
        directory / f"{timestamp}.isaacteleop.{os.getpid()}.native-{label}.log"
    )
    read_fd, write_fd = os.pipe()
    saved = os.fdopen(os.dup(fd), "w", buffering=1)
    os.dup2(write_fd, fd)
    os.close(write_fd)
    _saved[fd] = saved
    if fd == 2:
        sys.stderr = saved
        console_handler.setStream(saved)
    else:
        sys.stdout = saved
    pump = threading.Thread(
        target=_pump,
        args=(fd, read_fd, sink_path),
        name=f"isaacteleop-native-{label}",
        daemon=True,
    )
    pump.start()
    _pumps[fd] = pump
    atexit.register(_drain, fd)


def _drain(fd: int) -> None:
    """Drop this process's write end so the pump reaches EOF and lands the tail.

    The pump is a daemon thread, so without this the bytes still in the pipe at
    interpreter shutdown never reach the file. The wait is bounded because a
    surviving child still holding the write end would keep EOF from arriving.
    """
    saved = _saved.get(fd)
    if saved is None:
        return
    os.dup2(saved.fileno(), fd)
    pump = _pumps.get(fd)
    if pump is not None:
        pump.join(timeout=0.5)


def gate(level: int, console_handler: logging.StreamHandler) -> None:
    """Always capture fd 1 + fd 2 to file; mirror them to the terminal only at ``TRACE``.

    Both descriptors, not just fd 2: the CloudXR runtime worker used to
    ``dup2`` fd 1 to ``/dev/null`` and fd 2 to its own separate,
    never-mirrored file (``cloudxr/runtime.py``, removed) precisely because
    nothing here covered fd 1 -- covering both closes that gap and the fd 2
    race it created (two independent redirects of the same descriptor in one
    process). The mirror is decided when the pump drains, not when the bytes
    were written, so a level change mid-session applies to whatever is still
    in the pipe. Callers set the level once at startup, where that is
    invisible.
    """
    echo = level <= TRACE
    for fd in _FD_LABELS:
        _capture(fd, console_handler)
        _echo[fd] = echo
