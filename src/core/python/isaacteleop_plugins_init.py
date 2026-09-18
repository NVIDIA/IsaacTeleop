# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bundled Isaac Teleop plugin binaries.

Packaged inside the wheel so ``pip install isaacteleop`` alone is sufficient to run
them via :class:`~isaacteleop.teleop_session_manager.PluginManager` -- no separate
``cmake --install`` step required.
"""

from pathlib import Path


def plugin_search_path() -> Path:
    """Directory containing every bundled plugin's subdirectory (e.g. ``keyboard/``).

    Pass this to :class:`~isaacteleop.teleop_session_manager.PluginConfig.search_paths`.
    """
    return Path(__file__).resolve().parent
