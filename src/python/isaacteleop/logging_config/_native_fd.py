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

from ._core import TRACE, ensure_log_dir

_FD_LABELS = {1: "stdout", 2: "stderr"}

_saved: dict[int, TextIO] = {}
_sink_paths: dict[int, str] = {}
_mirrors: dict[int, threading.Thread] = {}
_echo: dict[int, bool] = {}


def _write_all(fd: int, data: bytes) -> None:
    """``os.write`` until *data* is gone; a tty or a full disk can short-write."""
    while data:
        data = data[os.write(fd, data) :]


def _mirror(fd: int, sink_path: str) -> None:
    """Tail *fd*'s capture file onto the terminal while echo is on.

    A convenience, never a step a writer waits on: the bytes reach the file
    without this thread, so falling behind loses nothing. The tail starts at
    end-of-file and drops what it reads while echo is off, so enabling echo
    mid-session shows what follows rather than a backlog.
    """
    try:
        with open(sink_path, "rb", buffering=0) as sink:
            sink.seek(0, os.SEEK_END)
            while True:
                chunk = sink.read(65536)
                if not chunk:
                    time.sleep(0.05)
                    continue
                saved = _saved.get(fd)
                if _echo.get(fd) and saved is not None:
                    _write_all(saved.fileno(), chunk)
    except OSError:
        pass


def _discard_if_empty(sink_path: str, owner_pid: int) -> None:
    """Remove a capture file nothing ever wrote to.

    Most processes that import isaacteleop emit no raw fd 1/2 output at all,
    and the file has to exist before the first byte can land in it, so without
    this every one of them leaves a pair of empty logs behind. Only the creator
    may unlink: a fork inherits this registration along with a descriptor still
    open on the file.
    """
    if os.getpid() != owner_pid:
        return
    try:
        if os.path.getsize(sink_path) == 0:
            os.unlink(sink_path)
    except OSError:
        pass


def _reserve_std_fds() -> None:
    """Make sure fds 1 and 2 are open before any allocation below.

    os.open() hands out the lowest free descriptor. If this process was started
    with stdout or stderr closed -- daemons do exactly that -- the capture file
    lands *on* the number we are about to dup2() over, and the duplicate meant
    to keep the terminal reachable ends up pointing at the capture file
    instead. Attaching /dev/null to a closed std fd first keeps every
    allocation clear of the two descriptors this module rebinds.
    """
    for std in (1, 2):
        try:
            os.fstat(std)
        except OSError:
            opened = os.open(os.devnull, os.O_WRONLY)
            if opened != std:
                os.dup2(opened, std)
                os.close(opened)


def _follows(stream: TextIO | None, fd: int) -> bool:
    """True when writes to *stream* go through *fd*, so rebinding *fd* moves them.

    Everything else -- a ``StringIO`` installed by ``contextlib.redirect_stdout``,
    a notebook's or test runner's own stream object, ``None`` on an interpreter
    started without stdio -- writes past the descriptor and is out of reach of
    the capture below, so it must stay exactly as the application set it.
    """
    try:
        return stream.fileno() == fd
    except (AttributeError, OSError, ValueError):
        return False


def _capture(fd: int, console_handler: logging.StreamHandler) -> None:
    """Point *fd* (1 or 2) at its own capture file; idempotent.

    Native code -- the CloudXR/Monado OpenXR runtime above all -- writes its
    diagnostics straight to fd 1/2 and cannot be routed into this logger tree:
    it exports no log hook and does not implement ``XR_EXT_debug_utils``, so
    the descriptor is the only seam. What comes out is raw text rather than
    records, hence a separate file per fd from the handler-formatted one.

    A file, never a pipe. A pipe refuses writes past 64 KiB until a reader
    empties it, and a reader in this process needs the GIL between reads while
    the native call doing the writing holds it -- ``oxr_bindings.cpp`` releases
    none -- so the two deadlock. A write to a file needs nothing else to run.

    ``sys.stdout``/``sys.stderr`` are moved onto a duplicate of the real
    descriptor instead of following it -- as is the console handler's stream,
    bound to whatever ``sys.stderr`` was when it was built -- so ``print()``,
    ``print(file=sys.stderr)``, and uncaught tracebacks stay on the terminal --
    without this, ordinary ``print()`` calls (targeting fd 1 by default)
    would vanish into the capture file along with the native library's own
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
    directory = ensure_log_dir()
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    sink_path = str(
        directory / f"{timestamp}.isaacteleop.{os.getpid()}.native-{label}.log"
    )
    try:
        sink_fd = os.open(
            sink_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
        )
    except OSError:
        return  # leave the fd on the terminal rather than fail the import
    saved = os.fdopen(os.dup(fd), "w", buffering=1)
    os.dup2(sink_fd, fd)
    os.close(sink_fd)
    _saved[fd] = saved
    _sink_paths[fd] = sink_path
    if fd == 2:
        if _follows(sys.stderr, fd):
            sys.stderr = saved
        if _follows(console_handler.stream, fd):
            console_handler.setStream(saved)
    elif _follows(sys.stdout, fd):
        sys.stdout = saved
    atexit.register(_discard_if_empty, sink_path, os.getpid())


def _start_mirror(fd: int) -> None:
    """Start *fd*'s tail thread once, on the first gate that asks for echo.

    Not started alongside the capture: ``set_console_level`` can drop to
    ``TRACE`` at any point, and a session that never does should not carry the
    thread.
    """
    if fd in _mirrors or fd not in _sink_paths:
        return
    mirror = threading.Thread(
        target=_mirror,
        args=(fd, _sink_paths[fd]),
        name=f"isaacteleop-native-{_FD_LABELS[fd]}",
        daemon=True,
    )
    mirror.start()
    _mirrors[fd] = mirror


def gate(level: int, console_handler: logging.StreamHandler) -> None:
    """Always capture fd 1 + fd 2 to file; mirror them to the terminal only at ``TRACE``.

    Both descriptors, not just fd 2: the CloudXR runtime worker used to
    ``dup2`` fd 1 to ``/dev/null`` and fd 2 to its own separate,
    never-mirrored file (``cloudxr/runtime.py``, removed) precisely because
    nothing here covered fd 1 -- covering both closes that gap and the fd 2
    race it created (two independent redirects of the same descriptor in one
    process).
    """
    echo = level <= TRACE
    for fd in _FD_LABELS:
        _capture(fd, console_handler)
        _echo[fd] = echo
        if echo:
            _start_mirror(fd)
