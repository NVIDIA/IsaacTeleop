# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unified ImGui UI for retargeting engine - parameter tuning and visualization.

Provides a comprehensive ImGui interface for:
- Parameter tuning controls for multiple retargeters
- 3D visualization of retargeting state
- Real-time graphs and plots
- Multiple layout modes (tabs, vertical, horizontal, floating)

This module requires imgui and glfw to be installed:
    pip install teleopcore[ui]
    
Or manually:
    pip install imgui[glfw]

Module Structure:
-----------------
- multi_retargeter_tuning_ui: Main UI class (MultiRetargeterTuningUIImGui)
- layouts: Layout modes and layout rendering (LayoutMode, LayoutRenderer)
- parameter_ui: Parameter controls rendering (ParameterRenderer)
- perf_stats_ui: Performance statistics display (PerfStatsRenderer)
- renderer_3d_gl: OpenGL 3D scene rendering (Renderer3DGL)
- graph_renderer: Graph/plot rendering (GraphRenderer)
- camera: Camera state and control (CameraState, CameraController)
- math_utils: Math utilities (projection, quaternion ops)
"""

try:
    # Main UI class and layout modes (primary public API)
    from .multi_retargeter_tuning_ui import (
        MultiRetargeterTuningUIImGui,
        LayoutModeImGui,
    )
    from .layouts import LayoutMode, LayoutRenderer
    
    # Rendering components (for advanced users)
    from .renderer_3d_gl import Renderer3DGL
    from .graph_renderer import GraphRenderer
    from .parameter_ui import ParameterRenderer, render_parameter_control
    from .perf_stats_ui import PerfStatsRenderer
    
    # Camera components (for advanced users)
    from .camera import CameraState, CameraController
    
    # Math utilities (for advanced users)
    from .math_utils import (
        quat_rotate_vector,
        project_3d_to_2d,
    )

    __all__ = [
        # Primary public API
        "MultiRetargeterTuningUIImGui",
        "LayoutModeImGui",
        "LayoutMode",
        
        # Rendering components
        "LayoutRenderer",
        "Renderer3DGL",
        "GraphRenderer",
        "ParameterRenderer",
        "render_parameter_control",
        "PerfStatsRenderer",
        
        # Camera components
        "CameraState",
        "CameraController",
        
        # Math utilities
        "quat_rotate_vector",
        "project_3d_to_2d",
    ]
except ImportError as e:
    import sys
    error_msg = (
        "\n"
        "ImGui UI dependencies are not installed.\n"
        "Install with: pip install teleopcore[ui]\n"
        f"Original error: {e}\n"
    )
    print(error_msg, file=sys.stderr)
    raise ImportError(error_msg) from e
