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
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

ROOT_LOGGER_NAME = "isaacteleop"

LINE_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)-5s] [%(name)s] [pid:%(process)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DEFAULT_LOG_DIR = Path("~/.isaacteleop/logs").expanduser()
_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_FILE_BACKUP_COUNT = 5

# Below DEBUG (10). Default level for loggers wrapping third-party/vendor
# output, so vendor chatter is silent unless a handler/logger explicitly
# lowers its threshold to TRACE.
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _trace(self: logging.Logger, msg: object, *args: object, **kwargs: object) -> None:
    if self.isEnabledFor(TRACE):
        self._log(TRACE, msg, args, **kwargs)


logging.Logger.trace = _trace

_LEVEL_NAMES = {
    "trace": TRACE,
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
            raise ValueError(
                f"target must be 'logger_name', 'content', or 'both', got {target!r}"
            )
        self._regex = re.compile(pattern)
        self._target = target

    def filter(self, record: logging.LogRecord) -> bool:
        return (
            self._target in ("logger_name", "both")
            and bool(self._regex.search(record.name))
        ) or (
            self._target in ("content", "both")
            and bool(self._regex.search(record.getMessage()))
        )


_lock = threading.Lock()
_console_handler: logging.StreamHandler | None = None
_console_filter: KeywordFilter | None = None
_filter_pattern: str | None = None
_filter_target: str = "both"


def _ensure_console_handler() -> logging.StreamHandler:
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
        root.setLevel(
            TRACE
        )  # handlers filter; the logger itself must stay maximally permissive
        root.addHandler(handler)
        _console_handler = handler
        return _console_handler


_native_stderr: tuple[TextIO, TextIO] | None = None


def _gate_native_stderr(level: int) -> None:
    """Send fd 2 to ``/dev/null`` unless the console is showing ``TRACE``.

    Native code -- the CloudXR/Monado OpenXR runtime above all -- writes its
    diagnostics straight to fd 2 and cannot be routed into this logger tree:
    it exports no log hook and does not implement ``XR_EXT_debug_utils``, so
    the descriptor is the only seam. ``sys.stderr`` is moved onto a duplicate
    of the real descriptor instead of following fd 2, so tracebacks and
    ``print(file=sys.stderr)`` stay visible. Processes forked afterwards
    inherit the redirection; the C++ console sink writes to fd 1 and is
    unaffected.
    """
    global _native_stderr
    discard = level > TRACE
    if discard == (_native_stderr is not None):
        return
    if _native_stderr is None:
        real_stderr = os.fdopen(os.dup(2), "w", buffering=1)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, 2)
        os.close(devnull_fd)
        _native_stderr = (real_stderr, sys.stderr)
        sys.stderr = real_stderr
        _ensure_console_handler().setStream(real_stderr)
    else:
        real_stderr, original = _native_stderr
        os.dup2(real_stderr.fileno(), 2)
        sys.stderr = original
        _native_stderr = None
        # Detach the handler before closing, or its flush hits a closed stream.
        _ensure_console_handler().setStream(original)
        real_stderr.close()


def set_console_level(level: int | str) -> None:
    """Set the console handler's display threshold.

    Independent of the file handler, which always captures everything
    regardless of what the console is set to.
    """
    resolved = _resolve_level(level)
    _ensure_console_handler().setLevel(resolved)
    _gate_native_stderr(resolved)


def set_console_filter(pattern: str | None, target: str = "both") -> None:
    """Set the console handler's keyword filter, or clear it if *pattern* is ``None``."""
    handler = _ensure_console_handler()
    global _console_filter, _filter_pattern, _filter_target
    if _console_filter is not None:
        handler.removeFilter(_console_filter)
        _console_filter = None
    _filter_pattern = pattern
    _filter_target = target
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

    One file per process (the name includes a start-time timestamp and the
    pid): concurrent processes rotating the same file can corrupt it, so
    each process gets its own; the timestamp makes the file's creation time
    greppable/sortable from its name and guards against a reused pid
    colliding with an older run's file, while the pid still guards against
    two processes starting in the same second. Always captures everything
    (``DEBUG``+) — not user-configurable, unlike the console handler's level.
    """
    global _file_handler
    if _file_handler is not None:
        return _file_handler
    with _lock:
        if _file_handler is not None:
            return _file_handler
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        handler = RotatingFileHandler(
            log_dir / f"isaacteleop.{timestamp}.{os.getpid()}.log",
            maxBytes=_FILE_MAX_BYTES,
            backupCount=_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(LINE_FORMAT, datefmt=DATE_FORMAT))
        handler.setLevel(logging.DEBUG)
        logging.getLogger(ROOT_LOGGER_NAME).addHandler(handler)
        _file_handler = handler
        return _file_handler


class _Unset:
    """Sentinel type for :func:`configure`'s "leave this parameter as-is" default.

    Distinct from ``None``, which for *filter* means "explicitly clear the
    filter" rather than "the caller didn't pass this parameter".
    """

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


def configure(
    level: int | str | _Unset = UNSET,
    filter: str | None | _Unset = UNSET,
    filter_target: str | _Unset = UNSET,
) -> None:
    """Partially overlay the console handler's display level and/or keyword filter.

    Each parameter defaults to :data:`UNSET`: an omitted parameter leaves
    whatever is already configured untouched, including a value set by an
    earlier ``configure()`` call. Passing ``filter=None`` is different from
    omitting *filter* — it explicitly clears a previously set filter.

    Only ever touches the console handler. The file handler always captures
    everything at ``DEBUG``+ regardless of what is passed here, and no
    logger's own default level (e.g. ``TRACE`` for third-party loggers) is
    affected.
    """
    if level is not UNSET:
        set_console_level(level)  # type: ignore[arg-type]

    if filter is not UNSET or filter_target is not UNSET:
        new_pattern = _filter_pattern if filter is UNSET else filter
        new_target = _filter_target if filter_target is UNSET else filter_target
        set_console_filter(new_pattern, target=new_target)  # type: ignore[arg-type]


_gate_native_stderr(_ensure_console_handler().level)
_ensure_file_handler()
