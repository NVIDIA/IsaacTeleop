# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ImGui-based UI for retargeting engine parameter tuning.

This module requires imgui and glfw to be installed:
    pip install 'isaacteleop[ui]'

Or manually:
    pip install imgui[glfw]
"""

try:
    from .multi_retargeter_tuning_ui import (
        LayoutModeImGui,
        MultiRetargeterTuningUIImGui,
    )

    __all__ = [
        "MultiRetargeterTuningUIImGui",
        "LayoutModeImGui",
    ]
except ImportError as e:
    error_msg = (
        "\n"
        "ImGui UI dependencies are not installed.\n"
        "Install with: pip install 'isaacteleop[ui]'\n"
        f"Original error: {e}\n"
    )
    # The raised ImportError already carries this message to the caller —
    # no separate print needed.
    raise ImportError(error_msg) from e
