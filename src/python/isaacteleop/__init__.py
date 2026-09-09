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
    log_bridge,
    logging_config,
    oxr,
    plugin_manager,
    schema,
    teleop_session_manager,
)

# Without this, in-process C++ keeps its own console/file sinks and its own
# ISAACTELEOP_LOG_LEVEL threshold, so logging_config.configure() silently governs only
# the Python half of the tree. Runs after logging_config, whose import-time setup builds
# the handlers these records land in; loggers created before this point are re-sinked by
# set_bridge_sink().
log_bridge.install_python_sink()

__all__ = [
    "log_bridge",
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
