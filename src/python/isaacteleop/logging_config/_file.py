# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The one rotating log file the session leader persists every record to."""

from __future__ import annotations

import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler

from ._core import DATE_FORMAT, LINE_FORMAT, ROOT_LOGGER_NAME, ensure_log_dir

_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_BACKUP_COUNT = 5

_lock = threading.Lock()
_handler: logging.Handler | None = None


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """A rotating handler whose files are ours alone.

    logging opens with plain ``open(..., 'a')``: mode ``0666 & ~umask`` -- 0644
    under the usual umask -- and it follows a symlink already sitting at the
    path. The native capture file beside it is opened 0600 with ``O_NOFOLLOW``,
    and the same reasoning applies here. ``ensure_log_dir()`` makes the *default*
    directory 0700, but an operator's ``ISAACTELEOP_LOG_DIR`` only has to be
    owned by us, so a world-writable one is accepted; and the file name is
    guessable, being a timestamp to the second plus a pid anyone can read out
    of /proc.
    """

    def _open(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.baseFilename, flags, 0o600)
        return open(
            fd,
            self.mode,
            encoding=self.encoding,
            errors=getattr(self, "errors", None),
        )


def ensure_handler() -> logging.Handler:
    """Create and attach the file handler on first use; idempotent after that.

    One file per process (the name leads with a start-time timestamp and
    ends with the pid): concurrent processes rotating the same file can
    corrupt it, so each process gets its own; the leading timestamp makes
    the run's start time the first thing the name says, keeps a run's files
    adjacent whatever produced them, and guards against a reused pid
    colliding with an older run's file, while the pid still guards against
    two processes starting in the same second. Always captures everything
    (``DEBUG``+) — not user-configurable, unlike the console handler's level.
    """
    global _handler
    if _handler is not None:
        return _handler
    with _lock:
        if _handler is not None:
            return _handler
        directory = ensure_log_dir()
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        handler = _PrivateRotatingFileHandler(
            directory / f"{timestamp}.isaacteleop.{os.getpid()}.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(LINE_FORMAT, datefmt=DATE_FORMAT))
        handler.setLevel(logging.DEBUG)
        logging.getLogger(ROOT_LOGGER_NAME).addHandler(handler)
        _handler = handler
        return _handler
