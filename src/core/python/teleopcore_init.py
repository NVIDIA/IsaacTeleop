# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""TeleopCore - Teleoperation Core Library

This package provides Python bindings for teleoperation with Extended Reality I/O.
"""

__version__ = "1.0.0"

# Import submodules
from . import xrio
from . import oxr
from . import plugin_manager

__all__ = ["xrio", "oxr", "plugin_manager", "__version__"]
