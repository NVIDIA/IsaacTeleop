# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Names, line format, levels and log directory shared by every handler here."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

# Unix domain sockets, uids and O_NOFOLLOW are all POSIX-only, and this package
# is imported by isaacteleop/__init__.py -- so on Windows the alternative to
# branching here is an AttributeError out of `import isaacteleop`.
_POSIX = os.name == "posix"

ROOT_LOGGER_NAME = "isaacteleop"

LINE_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)-5s] [%(name)s] [pid:%(process)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Per-uid on POSIX, not a single shared /tmp/isaacteleop: a fixed path would be
# created by whichever user gets there first, and every other user on the
# machine then fails to create anything inside it -- a PermissionError out of
# `import isaacteleop`. Windows needs no suffix: GetTempPath() is already
# per-user, and there is no uid to name the directory after.
_DEFAULT_LOG_DIR = (
    Path(f"/tmp/isaacteleop-{os.getuid()}/logs")
    if _POSIX
    else Path(tempfile.gettempdir()) / "isaacteleop" / "logs"
)

# Below DEBUG (10). Default level for loggers wrapping third-party/vendor
# output, so vendor chatter is silent unless a handler/logger explicitly
# lowers its threshold to TRACE. Registered as a name so `%(levelname)s`
# renders it; there is deliberately no `Logger.trace()` method, which would
# mean patching the stdlib class for every logger in the process -- use
# `logger.log(TRACE, ...)`.
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

_LEVEL_NAMES = {
    "trace": TRACE,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

# spdlog spells its levels exactly like the keys above, so a name round-trips straight
# into ISAACTELEOP_LOG_LEVEL for out-of-process C++.
_LEVEL_NAME_BY_VALUE = {value: name for name, value in _LEVEL_NAMES.items()}


def _move_above_std(fd: int) -> int:
    """Relocate *fd* clear of 0/1/2, leaving any closed std fd closed."""
    low: list[int] = []
    try:
        while fd <= 2:
            low.append(fd)
            fd = os.dup(fd)
    except OSError:
        for spare in low:
            try:
                os.close(spare)
            except OSError:
                pass
        raise
    for spare in low:
        os.close(spare)
    return fd


def resolve_level(level: int | str) -> int:
    """Accept either a stdlib level int or one of the names in ``_LEVEL_NAMES``."""
    if isinstance(level, str):
        try:
            return _LEVEL_NAMES[level.lower()]
        except KeyError:
            raise ValueError(
                f"Unknown log level {level!r}; expected one of {sorted(_LEVEL_NAMES)}"
            ) from None
    return level


def env_console_level() -> int:
    """Console threshold from ``ISAACTELEOP_LOG_LEVEL``, or ``INFO`` if unset.

    The same variable and vocabulary ``log_bridge/cpp/sink_config.cpp``'s
    ``console_level()`` reads: the six names above, case-insensitively, or a
    stdlib level number, which is taken literally here and bucketed to the
    nearest spdlog level there. Anything else falls back to ``INFO`` rather
    than raising -- ``install()`` runs from ``import isaacteleop``.
    """
    raw = os.environ.get("ISAACTELEOP_LOG_LEVEL")
    if not raw:
        return logging.INFO
    raw = raw.strip()
    digits = raw[1:] if raw[:1] in ("+", "-") else raw
    if digits.isascii() and digits.isdecimal():
        normalized = digits.lstrip("0") or "0"
        # Avoid Python's integer-string limit on an import-time environment
        # value; C++ already collapses out-of-range numbers to trace or off.
        if len(normalized) > 2 or int(normalized) > logging.CRITICAL:
            return TRACE if raw.startswith("-") else logging.CRITICAL + 1
        value = int(normalized)
        return -value if raw.startswith("-") else value
    return _LEVEL_NAMES.get(raw.lower(), logging.INFO)


def log_dir() -> Path:
    """Directory every log file of this session lands in.

    ``/tmp/isaacteleop-<uid>/logs`` (a per-user temp directory on Windows)
    unless ``ISAACTELEOP_LOG_DIR`` overrides it;
    the C++ side resolves the same pair (``log_bridge/cpp/sink_config.cpp``).
    Use :func:`ensure_log_dir` when the directory has to exist.
    """
    override = os.environ.get("ISAACTELEOP_LOG_DIR")
    try:
        directory = Path(override).expanduser() if override else _DEFAULT_LOG_DIR
    except RuntimeError:
        # expanduser() raises RuntimeError, not OSError, for a ~ path it cannot
        # resolve: no HOME and no passwd entry, which is what `--user 1234` in a
        # container looks like. Callers here guard against OSError only.
        directory = _DEFAULT_LOG_DIR

    try:
        directory = directory.absolute()
    except OSError:
        pass
    # Children may chdir before their first C++ logger is created. Publishing
    # the expanded absolute path also covers platform-specific ~ and temp-dir
    # rules that C++ cannot reproduce exactly.
    os.environ["ISAACTELEOP_LOG_DIR"] = str(directory)
    return directory


def ensure_private_dir(directory: Path) -> Path:
    """*directory*, created if needed, owner-only on what this call created.

    Each created component, not only the leaf: the default log directory is
    ``<runtime dir>/logs`` and the runtime directory is where the log socket
    lives, so ``parents=True`` alone left that one at the umask. A path the
    operator chose keeps whatever permissions the operator gave it.

    Confidentiality rests on this 0700 and on the ``O_EXCL | O_NOFOLLOW`` every
    file here is created with (``_file.py``, ``_native_fd.py``, and the C++
    half's ``unique_log_path``), not on vetting the path: under a directory
    another local user got to first, those flags refuse a planted name rather
    than write through it, which costs a handler and discloses nothing.

    Raises:
        OSError: if the directory cannot be created, or its mode not set.
    """
    missing = []
    probe = directory
    while not probe.exists() and probe != probe.parent:
        missing.append(probe)
        probe = probe.parent

    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        return directory
    if _POSIX:
        for component in missing:
            component.chmod(0o700)
    return directory


def ensure_log_dir() -> Path:
    """:func:`log_dir`, created if needed."""
    return ensure_private_dir(log_dir())
