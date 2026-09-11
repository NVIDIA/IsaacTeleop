# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Names, line format, levels and log directory shared by every handler here."""

from __future__ import annotations

import logging
import os
from pathlib import Path

ROOT_LOGGER_NAME = "isaacteleop"

LINE_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)-5s] [%(name)s] [pid:%(process)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Per-uid, not a single shared /tmp/isaacteleop: a fixed path is created by
# whichever user gets there first, with that user's umask, and every other user
# on the machine then fails to create anything inside it -- which surfaces as
# PermissionError out of `import isaacteleop`. The uid also keeps one user's
# records, native-fd captures and log socket out of everyone else's reach.
_DEFAULT_LOG_DIR = Path(f"/tmp/isaacteleop-{os.getuid()}/logs")

_LEVEL_NAMES = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

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

    ``/tmp/isaacteleop-<uid>/logs`` unless ``ISAACTELEOP_LOG_DIR`` overrides it;
    the C++ side resolves the same pair (``log_bridge/cpp/sink_config.cpp``).
    Use :func:`ensure_log_dir` when the directory has to exist.
    """
    override = os.environ.get("ISAACTELEOP_LOG_DIR")
    return Path(override).expanduser() if override else _DEFAULT_LOG_DIR


def ensure_log_dir() -> Path:
    """:func:`log_dir`, created if needed and confirmed to belong to us.

    Created 0700 so the records, the raw fd captures beside them and the log
    socket are not readable -- or plantable -- by other users of the machine.
    mkdir()'s mode is masked by the umask, so the bits are set explicitly, and
    only on a directory this call created: a path the operator chose through
    ISAACTELEOP_LOG_DIR keeps whatever permissions the operator gave it.

    The ownership check refuses a directory some other user got to first, which
    under /tmp is the classic way to have another process write through a
    symlink on your behalf.
    """
    directory = log_dir()
    created = False
    try:
        directory.mkdir(parents=True, exist_ok=False)
        created = True
    except FileExistsError:
        pass
    if created:
        directory.chmod(0o700)

    info = directory.stat()
    if info.st_uid != os.getuid():
        raise PermissionError(
            f"Refusing to log into {directory}: owned by uid {info.st_uid}, "
            f"not {os.getuid()}. Set ISAACTELEOP_LOG_DIR to a directory you own."
        )
    return directory
