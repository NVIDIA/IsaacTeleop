# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Central ``logging`` configuration for the ``isaacteleop`` logger tree.

One console handler on the root ``isaacteleop`` logger, so every
``isaacteleop.<module>[.<ClassName>]`` logger -- in this package or in
examples -- shares one console format, instead of each entry point building
its own handler.

``isaacteleop/__init__.py`` calls :func:`install` once; importing this package
on its own configures nothing. Applications then narrow the console view::

    from isaacteleop import logging_config

    logging_config.set_console_level("debug")
    logging_config.set_console_filter("manus", target="logger_name")
"""

from ._console import set_console_filter, set_console_level, set_logger_colors
from ._core import DATE_FORMAT, LINE_FORMAT, TRACE

# Not in __all__: the bootstrap ``isaacteleop/__init__.py`` calls once. Importing it
# here is what makes ``logging_config.install()`` resolve; nothing else should call it.
from ._setup import install as install
from ._setup import set_propagate_to_root

__all__ = [
    "DATE_FORMAT",
    "LINE_FORMAT",
    "TRACE",
    "set_console_filter",
    "set_console_level",
    "set_logger_colors",
    "set_propagate_to_root",
]
