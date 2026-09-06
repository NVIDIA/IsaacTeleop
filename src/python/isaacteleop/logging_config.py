# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Central ``logging`` configuration for the ``isaacteleop`` logger tree.

Attaches one console handler to the root ``isaacteleop`` logger so any logger
named ``isaacteleop.<module>[.<ClassName>]`` — anywhere in the package, in
examples, or (once bridged) from C++ — is visible through one consistently
formatted, independently filterable view, instead of each entry point
building its own ad-hoc ``logging.basicConfig()``.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT_LOGGER_NAME = "isaacteleop"

LINE_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)-5s] [%(name)s] [pid:%(process)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DEFAULT_LOG_DIR = Path("~/.isaacteleop/logs").expanduser()
_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_FILE_BACKUP_COUNT = 5

_LEVEL_NAMES = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def _resolve_level(level: int | str) -> int:
    """Accept either a stdlib level int or one of the names in ``_LEVEL_NAMES``."""
    if isinstance(level, str):
        try:
            return _LEVEL_NAMES[level.lower()]
        except KeyError:
            raise ValueError(
                f"Unknown log level {level!r}; expected one of {sorted(_LEVEL_NAMES)}"
            ) from None
    return level


class KeywordFilter(logging.Filter):
    """Keep only records whose logger name and/or message match *pattern*."""

    def __init__(self, pattern: str, target: str = "both") -> None:
        super().__init__()
        if target not in ("logger_name", "content", "both"):
            raise ValueError(f"target must be 'logger_name', 'content', or 'both', got {target!r}")
        self._regex = re.compile(pattern)
        self._target = target

    def filter(self, record: logging.LogRecord) -> bool:
        if self._target in ("logger_name", "both") and self._regex.search(record.name):
            return True
        if self._target in ("content", "both") and self._regex.search(record.getMessage()):
            return True
        return False


_lock = threading.Lock()
_console_handler: logging.Handler | None = None
_console_filter: KeywordFilter | None = None


def _ensure_console_handler() -> logging.Handler:
    """Create and attach the console handler on first use; idempotent after that."""
    global _console_handler
    if _console_handler is not None:
        return _console_handler
    with _lock:
        if _console_handler is not None:
            return _console_handler
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LINE_FORMAT, datefmt=DATE_FORMAT))
        handler.setLevel(logging.INFO)
        root = logging.getLogger(ROOT_LOGGER_NAME)
        root.setLevel(logging.DEBUG)  # handlers filter; the logger itself must stay permissive
        root.addHandler(handler)
        _console_handler = handler
        return _console_handler


def set_console_level(level: int | str) -> None:
    """Set the console handler's display threshold.

    Independent of the file handler, which always captures everything
    regardless of what the console is set to.
    """
    _ensure_console_handler().setLevel(_resolve_level(level))


def set_console_filter(pattern: str | None, target: str = "both") -> None:
    """Set the console handler's keyword filter, or clear it if *pattern* is ``None``."""
    handler = _ensure_console_handler()
    global _console_filter
    if _console_filter is not None:
        handler.removeFilter(_console_filter)
        _console_filter = None
    if pattern is not None:
        _console_filter = KeywordFilter(pattern, target=target)
        handler.addFilter(_console_filter)


def get_logger(name: str, cls: type | None = None) -> logging.Logger:
    """Return the logger for *name* (normally ``__name__``), suffixed with *cls*'s name.

    Only needed when a module defines more than one loggable class; otherwise
    ``get_logger(__name__)`` and ``logging.getLogger(__name__)`` are equivalent.
    """
    if cls is not None:
        name = f"{name}.{cls.__name__}"
    return logging.getLogger(name)


def _log_dir() -> Path:
    override = os.environ.get("ISAACTELEOP_LOG_DIR")
    return Path(override).expanduser() if override else DEFAULT_LOG_DIR


_file_handler: logging.Handler | None = None


def _ensure_file_handler() -> logging.Handler:
    """Create and attach the file handler on first use; idempotent after that.

    One file per process (the name includes the pid): concurrent processes
    rotating the same file can corrupt it, so each process gets its own.
    Always captures everything (``DEBUG``+) — not user-configurable, unlike
    the console handler's level.
    """
    global _file_handler
    if _file_handler is not None:
        return _file_handler
    with _lock:
        if _file_handler is not None:
            return _file_handler
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / f"isaacteleop.{os.getpid()}.log",
            maxBytes=_FILE_MAX_BYTES,
            backupCount=_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(LINE_FORMAT, datefmt=DATE_FORMAT))
        handler.setLevel(logging.DEBUG)
        logging.getLogger(ROOT_LOGGER_NAME).addHandler(handler)
        _file_handler = handler
        return _file_handler


_ensure_console_handler()
_ensure_file_handler()
