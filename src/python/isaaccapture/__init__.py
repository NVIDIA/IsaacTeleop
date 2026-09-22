# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop - Teleoperation Core Library

This package provides Python bindings for teleoperation with Device I/O.
"""

from importlib.metadata import PackageNotFoundError, distribution, version

# The transition distribution owns no code; legacy wheels still own isaacteleop/.
# Wheel installers do not execute this import-time check.
try:
    _legacy_files = distribution("isaacteleop").files or ()
except PackageNotFoundError:
    _legacy_files = ()
if any(path.parts[0] == "isaacteleop" for path in _legacy_files):
    raise ImportError(
        "The legacy 'isaacteleop' distribution is still installed in this environment. "
        "Run `python -m pip install --upgrade isaaccapture` "
        "with your intended version and extras to replace it."
    )

try:
    __version__ = version("isaaccapture")
except PackageNotFoundError:
    # Fallback for local source-tree usage before wheel/package installation.
    __version__ = "0+unknown"

# Import submodules.
from . import deviceio_trackers
from . import deviceio_session
from . import deviceio
from . import oxr
from . import plugin_manager
from . import schema
from . import teleop_session_manager
from . import cloudxr

__all__ = [
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
