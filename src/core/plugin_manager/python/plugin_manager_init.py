# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""TeleopCore Plugin Manager - Plugin Management Module

This module provides functionality to discover and manage Teleop plugins.
"""

from ._plugin_manager import (
    Plugin,
    PluginManager,
)

__all__ = [
    "Plugin",
    "PluginManager",
]

