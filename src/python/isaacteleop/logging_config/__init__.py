# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Central ``logging`` configuration for the ``isaacteleop`` logger tree.

One console handler on the root ``isaacteleop`` logger, so every
``isaacteleop.<module>[.<ClassName>]`` logger -- in this package, in examples,
from in-process C++ via :mod:`isaacteleop.log_bridge`, or from a worker
process this session spawned -- shares one console format, instead of each
entry point building its own handlers. Records from other processes and from
standalone C++ arrive over a socket; see ``_forwarding.py`` for that design.

``isaacteleop/__init__.py`` calls :func:`install` once; importing this package
on its own configures nothing. Applications then narrow the console view::

    from isaacteleop import logging_config

    logging_config.set_console_level("debug")
    logging_config.set_console_filter("manus", target="logger_name")
"""

from ._console import (
    KeywordFilter,
    set_console_filter,
    set_console_level,
    set_logger_colors,
)
from ._core import (
    DATE_FORMAT,
    LINE_FORMAT,
    ROOT_LOGGER_NAME,
    TRACE,
    get_logger,
    log_dir,
)
from ._setup import install

__all__ = [
    "DATE_FORMAT",
    "KeywordFilter",
    "LINE_FORMAT",
    "ROOT_LOGGER_NAME",
    "TRACE",
    "get_logger",
    "install",
    "log_dir",
    "set_console_filter",
    "set_console_level",
    "set_logger_colors",
]
