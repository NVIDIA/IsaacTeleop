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

_DEFAULT_LOG_DIR = Path("/tmp/isaacteleop/logs")

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

    ``/tmp/isaacteleop/logs`` unless ``ISAACTELEOP_LOG_DIR`` overrides it; the C++
    side resolves the same pair (``log_bridge/cpp/sink_config.cpp``).
    """
    override = os.environ.get("ISAACTELEOP_LOG_DIR")
    return Path(override).expanduser() if override else _DEFAULT_LOG_DIR
