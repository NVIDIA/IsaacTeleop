# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Names, line format, levels and log directory shared by every handler here."""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from pathlib import Path

# Unix domain sockets, uids and O_NOFOLLOW are all POSIX-only, and this package
# is imported by isaacteleop/__init__.py -- so on Windows the alternative to
# branching here is an AttributeError out of `import isaacteleop`.
_POSIX = os.name == "posix"

ROOT_LOGGER_NAME = "isaacteleop"

LINE_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)-5s] [%(name)s] [pid:%(process)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Per-uid on POSIX, not a single shared /tmp/isaacteleop: a fixed path is
# created by whichever user gets there first, with that user's umask, and every
# other user on the machine then fails to create anything inside it -- which
# surfaces as PermissionError out of `import isaacteleop`. The uid also keeps
# one user's records, native-fd captures and log socket out of everyone else's
# reach. Windows needs no such suffix: GetTempPath() is already per-user
# (%LOCALAPPDATA%\Temp), and it has no uid to name the directory after.
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
        # expanduser() raises RuntimeError, not OSError, for a path starting
        # with ~ that it cannot resolve: no HOME, and no passwd entry for this
        # uid, which is what a container started with `--user 1234` looks
        # like. Every caller here guards against OSError only, so this escaped
        # install() and took `import isaacteleop` down with it. The default is
        # always resolvable -- it is built from os.getuid() alone.
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


def ensure_private_dir(directory: Path, *, remedy: str = "") -> Path:
    """*directory*, created if needed and confirmed to belong to us.

    Created 0700 so the records, the raw fd captures beside them and the log
    socket are not readable -- or plantable -- by other users of the machine.
    mkdir()'s mode is masked by the umask, so the bits are set explicitly, and
    only on a directory this call created: a path the operator chose keeps
    whatever permissions the operator gave it.

    The ownership check refuses a directory some other user got to first, which
    under /tmp is the classic way to have another process write through a
    symlink on your behalf. It covers the directory *and the directory it sits
    in*, by ``lstat``, because owning a leaf inside someone else's directory
    buys nothing: they can move it aside. Both steps are POSIX-only: chmod
    moves nothing but the read-only bit on Windows, st_uid is always 0 there,
    and the shared-directory threat they answer does not arise under a per-user
    temp path.

    Args:
        directory: the path to create and vet.
        remedy: appended to the refusal message, to name the setting a caller
            can change.

    Raises:
        PermissionError: if *directory* is not our directory, or if an ancestor
            is owned by neither us nor root, or is group/world-writable without
            the sticky bit.
    """
    # Every component this call is about to create, shallowest last. mkdir()'s
    # mode is masked by the umask, so each one needs the bits set explicitly --
    # and each one, not just the leaf: the default log directory is
    # <runtime dir>/logs, so creating it with parents=True was leaving the
    # runtime directory the log socket lives in at whatever the umask gave it.
    missing = []
    probe = directory
    while not probe.exists() and probe != probe.parent:
        missing.append(probe)
        probe = probe.parent

    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        missing = []
    if not _POSIX:
        return directory

    for component in missing:
        component.chmod(0o700)

    # lstat, not stat: a symlink planted where the directory should be carries
    # the planter's uid, while whatever it points at may well be ours -- which
    # is exactly what makes planting it worth doing. stat() would follow it and
    # report the target's owner, so the check passed on the one shape it was
    # written to refuse.
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise PermissionError(
            f"Refusing to use {directory}: it is not a directory owned by "
            f"uid {os.getuid()}.{remedy}"
        )

    # Every ancestor matters: owning the immediate parent buys nothing when
    # someone else can replace that parent from the level above it.
    parent = directory.parent
    if parent != directory:
        previous = directory
        while parent != previous:
            parent_info = parent.lstat()
            if parent_info.st_uid not in (os.getuid(), 0):
                raise PermissionError(
                    f"Refusing to use {directory}: ancestor {parent} is owned "
                    f"by uid {parent_info.st_uid}, not {os.getuid()} or root."
                    f"{remedy}"
                )
            if not (
                stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
            ):
                raise PermissionError(
                    f"Refusing to use {directory}: ancestor {parent} is not a "
                    f"directory.{remedy}"
                )
            parent_mode = stat.S_IMODE(parent_info.st_mode)
            shared_write = parent_mode & (stat.S_IWGRP | stat.S_IWOTH)
            if (
                not stat.S_ISLNK(parent_info.st_mode)
                and shared_write
                and not parent_mode & stat.S_ISVTX
            ):
                raise PermissionError(
                    f"Refusing to use {directory}: ancestor {parent} is "
                    f"group/world-writable without the sticky bit.{remedy}"
                )
            previous = parent
            parent = parent.parent
    return directory


def ensure_log_dir() -> Path:
    """:func:`log_dir`, created if needed and confirmed to belong to us."""
    return ensure_private_dir(
        log_dir(), remedy=" Set ISAACTELEOP_LOG_DIR to a directory you own."
    )
