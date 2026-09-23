# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The one rotating log file the session leader persists every record to."""

from __future__ import annotations

import atexit
import logging
import os
import stat
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ._core import (
    DATE_FORMAT,
    LINE_FORMAT,
    ROOT_LOGGER_NAME,
    TRACE,
    _move_above_std,
    ensure_log_dir,
)

_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_BACKUP_COUNT = 5

_lock = threading.Lock()
_handler: logging.Handler | None = None


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """A rotating handler whose files are ours alone.

    logging opens with plain ``open(..., 'a')``: mode ``0666 & ~umask`` and it
    follows a symlink already sitting at the path. The name is guessable -- a
    timestamp to the second plus a pid anyone can read out of /proc -- and an
    operator's ``ISAACTELEOP_LOG_DIR`` may be shared, so create exclusively,
    refuse a symlink, and set the mode in the creating call.
    """

    def _open(self):
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_APPEND
            | getattr(os, "O_NOFOLLOW", 0)
            # Windows opens a descriptor in text mode unless asked otherwise,
            # and the TextIOWrapper below already turns "\n" into os.linesep.
            # logging's own FileHandler never meets this because io.FileIO ORs
            # O_BINARY in when it opens by *name*; handing open() a ready-made
            # fd, as this does, skips that. Without it every line on disk ends
            # "\r\r\n".
            | getattr(os, "O_BINARY", 0)
        )
        fd = _move_above_std(os.open(self.baseFilename, flags, 0o600))
        try:
            return open(
                fd,
                self.mode,
                encoding=self.encoding,
                errors=getattr(self, "errors", None),
            )
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise


def _discard_if_empty(path: Path, identity: tuple[int, int], owner_pid: int) -> None:
    """Remove a session log file nothing was ever written to.

    Most processes that import isaacteleop emit no records of their own -- a
    CLI that only parses its arguments, a worker that exits on a bad config --
    and the handler opens the file when it is constructed, so without this
    every one of them leaves a 0-byte log behind. The capture file beside it is
    cleaned up the same way (``_native_fd._discard_if_empty``).

    An empty file is closed before unlink so Windows can remove it. A nonempty
    handler stays open for older atexit callbacks that may still log.

    Only the creator may unlink -- a fork inherits this registration -- and
    only while the path still names the file this process opened. That
    identity check also covers rotation for free: a rotated base file is a new
    inode, so a handler that ever rolled over is left alone along with its
    backups.
    """
    if os.getpid() != owner_pid:
        return
    handler = _handler
    if handler is None:
        return
    try:
        handler.acquire()
        try:
            if handler.stream is None:
                return
            handler.flush()
            opened = os.fstat(handler.stream.fileno())
            current = os.lstat(path)
            if not (
                stat.S_ISREG(current.st_mode)
                and (opened.st_dev, opened.st_ino) == identity
                and (current.st_dev, current.st_ino) == identity
                and current.st_size == 0
            ):
                return

            handler.close()
            current = os.lstat(path)
            if (
                stat.S_ISREG(current.st_mode)
                and (current.st_dev, current.st_ino) == identity
                and current.st_size == 0
            ):
                os.unlink(path)
        finally:
            handler.release()
    except (OSError, ValueError):
        return  # Best-effort atexit cleanup; nothing here may raise.


def ensure_handler() -> logging.Handler:
    """Create and attach the file handler on first use; idempotent after that.

    One file per process (the name leads with a start-time timestamp and
    ends with the pid): concurrent processes rotating the same file can
    corrupt it, so each process gets its own; the leading timestamp makes
    the run's start time the first thing the name says, keeps a run's files
    adjacent whatever produced them, and guards against a reused pid
    colliding with an older run's file, while the pid still guards against
    two processes starting in the same second. Always captures everything
    (``TRACE``+) — not user-configurable, unlike the console handler's level.
    """
    global _handler
    if _handler is not None:
        return _handler
    with _lock:
        if _handler is not None:
            return _handler
        directory = ensure_log_dir()
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        path = directory / f"{timestamp}.isaacteleop.{os.getpid()}.log"
        handler = _PrivateRotatingFileHandler(
            path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(LINE_FORMAT, datefmt=DATE_FORMAT))
        handler.setLevel(TRACE)
        logging.getLogger(ROOT_LOGGER_NAME).addHandler(handler)
        # Recorded now, from the descriptor the handler is holding: at exit the
        # path alone cannot say whether it still names this file.
        opened = os.fstat(handler.stream.fileno())
        atexit.register(
            _discard_if_empty, path, (opened.st_dev, opened.st_ino), os.getpid()
        )
        _handler = handler
        return _handler
