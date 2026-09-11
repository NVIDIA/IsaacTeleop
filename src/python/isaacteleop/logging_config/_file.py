# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The one rotating log file the session leader persists every record to."""

from __future__ import annotations

import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler

from ._core import DATE_FORMAT, LINE_FORMAT, ROOT_LOGGER_NAME, log_dir

_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_BACKUP_COUNT = 5

_lock = threading.Lock()
_handler: logging.Handler | None = None


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
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        handler = RotatingFileHandler(
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
