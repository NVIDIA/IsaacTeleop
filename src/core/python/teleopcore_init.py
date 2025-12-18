# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""TeleopCore - Teleoperation Core Library

This package provides Python bindings for teleoperation with Device I/O.
"""

__version__ = "1.0.0"

# Import submodules.
from . import deviceio
from . import oxr
from . import plugin_manager
from . import schema

__all__ = ["deviceio", "oxr", "plugin_manager", "schema", "__version__"]
