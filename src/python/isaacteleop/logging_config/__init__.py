# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Central ``logging`` configuration for the ``isaacteleop`` logger tree.

One console handler and one file handler on the root ``isaacteleop`` logger,
so every ``isaacteleop.<module>[.<ClassName>]`` logger -- in this package, in
examples, from in-process C++ via :mod:`isaacteleop.log_bridge`, or from a
worker process this session spawned -- shares one console format and lands in
one file, instead of each entry point building its own handlers. Records from
other processes and from standalone C++ arrive over a socket; see
``_forwarding.py`` for that design.

``isaacteleop/__init__.py`` calls :func:`install` once; importing this package
on its own configures nothing. Applications then narrow the console view::

    from isaacteleop import logging_config

    logging_config.set_console_level("debug")
    logging_config.set_console_filter("manus", target="logger_name")

The file handler always captures ``DEBUG`` and above regardless of that.

Diagnostics that no logger can reach -- the CloudXR/Monado OpenXR runtime and
the Manus SDK write their own lines straight to a file descriptor -- are handled
separately, and without taking the host process's descriptors away from it; see
``_native_api.py`` for that surface and ``_native_fd.py`` for the mechanism.
"""

from ._console import set_console_filter, set_console_level, set_logger_colors
from ._core import DATE_FORMAT, LINE_FORMAT, TRACE, log_dir
from ._native_api import (
    capture_native_output,
    native_capture_mode,
    native_capture_path,
    set_native_capture_mode,
    set_native_echo,
)

# Not in __all__: the bootstrap ``isaacteleop/__init__.py`` calls once. Importing it
# here is what makes ``logging_config.install()`` resolve; nothing else should call it.
from ._setup import install as install
from ._setup import set_propagate_to_root

__all__ = [
    "DATE_FORMAT",
    "LINE_FORMAT",
    "TRACE",
    "capture_native_output",
    "log_dir",
    "native_capture_mode",
    "native_capture_path",
    "set_console_filter",
    "set_console_level",
    "set_logger_colors",
    "set_native_capture_mode",
    "set_native_echo",
    "set_propagate_to_root",
]
