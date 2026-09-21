# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The one console handler on the ``isaacteleop`` root logger, and its knobs."""

from __future__ import annotations

import logging
import os
import re
import threading

from . import _forwarding, _native_fd
from ._core import (
    _LEVEL_NAME_BY_VALUE,
    DATE_FORMAT,
    LINE_FORMAT,
    ROOT_LOGGER_NAME,
    TRACE,
    resolve_level,
)


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


_ANSI_RESET = "\033[0m"

# One or more SGR sequences, which is all a colour needs -- ``\x1b[36m``,
# ``\x1b[38;2;255;136;0m``, or ``\x1b[1m\x1b[36m`` to combine. Deliberately excludes the
# rest of ANSI: a registered value is written to the terminal verbatim, so anything
# beyond SGR (cursor control, OSC, a bare newline) could reposition or reprogram the
# terminal, or split one record across lines.
_SGR_ESCAPE = re.compile(r"(?:\x1b\[[0-9;]*m)+")

# Exact logger name -> ANSI escape, stored verbatim as registered. Empty means every
# name renders in the terminal's default colour.
_logger_colors: dict[str, str] = {}


#: Yellow for WARNING, red for ERROR and above. Only these two: the point is that
#: they stand out from the INFO lines around them, which they cannot do if
#: everything is coloured. Compared with ``>=`` rather than looked up by value, so a
#: level between the stdlib's -- and TRACE, below them all -- lands on the right side.
_LEVEL_WARNING_COLOR = "\033[33m"
_LEVEL_ERROR_COLOR = "\033[31m"


def _level_color(levelno: int) -> str | None:
    """The whole-line emphasis for *levelno*, or ``None`` to leave it plain."""
    if levelno >= logging.ERROR:
        return _LEVEL_ERROR_COLOR
    if levelno >= logging.WARNING:
        return _LEVEL_WARNING_COLOR
    return None


class _LoggerNameColorFormatter(logging.Formatter):
    """Colours the line by level, and ``[%(name)s]`` by its registered emphasis.

    A warning is yellow and an error red, end to end, so the eye finds it without
    reading. A logger that has an emphasis colour keeps it inside that line, and
    the level colour **resumes** after the name rather than resetting to the
    terminal default -- the pid and the message belong to the same record and
    should keep reading as one::

        <yellow>[ts] [WARNING] [<emphasis>name<yellow>] [pid:N] message<reset>

    Escapes are emitted only when the handler's stream is a terminal. Everywhere
    else -- a pipe, a CI log, a file an operator redirected into -- they would be
    noise in text nobody can see colour in, and they would corrupt anything that
    parses the output.
    """

    def __init__(self, *args, handler: logging.StreamHandler, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Read at format time, not captured now: _native_fd's capture moves this
        # handler onto a duplicate of the real descriptor after the formatter is
        # built, and the answer has to follow the stream it ends up on.
        self._handler = handler

    def _is_terminal(self) -> bool:
        stream = getattr(self._handler, "stream", None)
        try:
            return bool(stream.isatty())
        except (AttributeError, OSError, ValueError):
            return False

    def format(self, record: logging.LogRecord) -> str:
        if not self._is_terminal():
            return super().format(record)

        level = _level_color(record.levelno)
        emphasis = _logger_colors.get(record.name)
        if level is None and emphasis is None:
            return super().format(record)

        # The record is shared with the file handler, which must stay escape-free:
        # callHandlers formats handlers one at a time on the emitting thread, so
        # restoring the name here keeps the substitution local to this call.
        original = record.name
        if emphasis is not None:
            record.name = f"{emphasis}{original}{level or _ANSI_RESET}"
        try:
            line = super().format(record)
        finally:
            record.name = original
        return f"{level}{line}{_ANSI_RESET}" if level is not None else line


_lock = threading.Lock()
_handler: logging.StreamHandler | None = None
_active_filter: KeywordFilter | None = None


def ensure_handler() -> logging.StreamHandler:
    """Create the console handler on first use; idempotent after that.

    Attached to the root logger only for the session leader -- a forwarding
    child still builds this object (``_native_fd.gate`` needs somewhere to
    redirect its stream bookkeeping to regardless of leader/child status), it
    just never receives records, so it never prints a local, second copy of
    what the leader's own console handler already shows once the record comes
    back through the forwarder.
    """
    global _handler
    if _handler is not None:
        return _handler
    with _lock:
        if _handler is not None:
            return _handler
        handler = logging.StreamHandler()
        handler.setFormatter(
            _LoggerNameColorFormatter(LINE_FORMAT, datefmt=DATE_FORMAT, handler=handler)
        )
        handler.setLevel(logging.INFO)
        root = logging.getLogger(ROOT_LOGGER_NAME)
        root.setLevel(
            TRACE
        )  # handlers filter; the logger itself must stay maximally permissive
        if _forwarding.socket_path() is None:
            root.addHandler(handler)
        _handler = handler
        return _handler


def set_console_level(level: int | str) -> None:
    """Set the console handler's display threshold.

    Independent of the file handler, which always captures everything
    regardless of what the console is set to.
    """
    resolved = resolve_level(level)
    handler = ensure_handler()
    handler.setLevel(resolved)
    _native_fd.gate(resolved, handler)
    # Plugin executables are fork+exec'd (core/plugin_manager) and so are out of reach of
    # the in-process bridge; they read their own console threshold from this variable.
    os.environ["ISAACTELEOP_LOG_LEVEL"] = _LEVEL_NAME_BY_VALUE.get(
        resolved, str(resolved)
    )


def set_console_filter(pattern: str | None, target: str = "both") -> None:
    """Set the console handler's keyword filter, or clear it if *pattern* is ``None``."""
    handler = ensure_handler()
    # Built before anything is torn down. KeywordFilter validates *target* and
    # compiles *pattern*, either of which can raise; clearing the active filter
    # first would leave the console unfiltered on a rejected argument.
    replacement = KeywordFilter(pattern, target=target) if pattern is not None else None

    global _active_filter
    if _active_filter is not None:
        handler.removeFilter(_active_filter)
    _active_filter = replacement
    if replacement is not None:
        handler.addFilter(replacement)


def set_logger_colors(colors: dict[str, str | None]) -> None:
    """Overlay the console emphasis colour of the ``[logger_name]`` field.

    *colors* maps an exact logger name to an SGR escape -- ``"\\033[36m"``,
    ``"\\033[38;2;255;136;0m"`` and the like, emitted as given -- or to ``None``
    to drop a colour set earlier. Names left out keep whatever they already
    have, and an unregistered logger renders in the terminal's default colour.
    Only the console handler is affected; the log file never receives escapes,
    and neither does a console stream that is not a terminal.

    Independent of the level colouring, and composes with it: on a warning or an
    error line the name is drawn in this colour and the level colour resumes
    after it, so the record still reads as one line.

    Raises:
        ValueError: if a value is not composed solely of SGR escapes.
    """
    ensure_handler()
    for name, color in colors.items():
        if color is None:
            _logger_colors.pop(name, None)
            continue
        if not _SGR_ESCAPE.fullmatch(color):
            raise ValueError(
                f"Colour for logger {name!r} must be one or more SGR escapes, such as "
                f"'\\033[36m' or '\\033[38;2;255;136;0m', got {color!r}"
            )
        _logger_colors[name] = color
