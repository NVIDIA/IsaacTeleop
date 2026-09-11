# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop - Teleoperation Core Library

This package provides Python bindings for teleoperation with Device I/O.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("isaacteleop")
except PackageNotFoundError:
    # Fallback for local source-tree usage before wheel/package installation.
    __version__ = "0+unknown"

# Import submodules.
from . import (
    cloudxr,
    deviceio,
    deviceio_session,
    deviceio_trackers,
    logging_config,
    oxr,
    plugin_manager,
    schema,
    teleop_session_manager,
)

# Builds the handlers every isaacteleop.* logger in this process emits through.
logging_config.install()

__all__ = [
    "logging_config",
    "deviceio_trackers",
    "deviceio_session",
    "deviceio",
    "oxr",
    "plugin_manager",
    "schema",
    "teleop_session_manager",
    "cloudxr",
    "__version__",
]
