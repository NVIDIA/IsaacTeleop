# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Layout modes and layout rendering for multi-retargeter UI.

Provides:
- LayoutMode enum for different layout configurations
- Layout renderers for tabs, vertical, horizontal, and floating layouts
"""

from enum import Enum
from typing import TYPE_CHECKING, Callable, Dict, Optional

import numpy as np
import imgui  # type: ignore[import-not-found]
import glfw  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from teleopcore.retargeting_engine.interface import ParameterState, VisualizationState
    from .camera import CameraState


class LayoutMode(Enum):
    """Layout modes for multi-retargeter ImGui UI."""
    TABS = "tabs"           # Tabbed interface (one tab per retargeter)
    VERTICAL = "vertical"   # Vertical stack (one below another)
    HORIZONTAL = "horizontal"  # Horizontal layout (side by side)
    FLOATING = "floating"   # Free-floating separate ImGui windows


class LayoutRenderer:
    """Renders different layout configurations.
    
    Handles:
    - Tabbed layout with one tab per retargeter
    - Vertical stack layout
    - Horizontal layout with columns
    - Floating windows layout
    """
    
    def __init__(
        self,
        render_retargeter_callback: Callable[[str, bool], None],
        render_viz_only_callback: Optional[Callable[[str], None]] = None
    ):
        """Initialize layout renderer.
        
        Args:
            render_retargeter_callback: Callback to render a retargeter's content.
                Signature: (name: str, inline_viz: bool) -> None
            render_viz_only_callback: Optional callback to render visualization-only content.
                Signature: (name: str) -> None
        """
        self._render_retargeter = render_retargeter_callback
        self._render_viz_only = render_viz_only_callback
        
        # Floating window state
        self._floating_windows_positioned = False
        self._floating_auto_arrange = False
    
    def trigger_auto_arrange(self) -> None:
        """Trigger auto-arrange for floating windows."""
        self._floating_auto_arrange = True
    
    def render_tabbed_layout(
        self,
        parameter_states: Dict[str, 'ParameterState'],
        visualization_states: Dict[str, 'VisualizationState']
    ) -> None:
        """Render tabbed layout with one tab per retargeter.
        
        Args:
            parameter_states: Dictionary of parameter states by name
            visualization_states: Dictionary of visualization states by name
        """
        # Build unified list of all retargeters
        all_retargeters = set(parameter_states.keys()) | set(visualization_states.keys())
        
        if imgui.begin_tab_bar("RetargeterTabs"):
            for name in sorted(all_retargeters):
                if imgui.begin_tab_item(name)[0]:
                    imgui.begin_child(f"tab_content_{name}", border=False)
                    
                    if name in parameter_states:
                        self._render_retargeter(name, True)
                    elif name in visualization_states and self._render_viz_only:
                        self._render_viz_only(name)
                    
                    imgui.end_child()
                    imgui.end_tab_item()
            imgui.end_tab_bar()
    
    def render_vertical_layout(
        self,
        parameter_states: Dict[str, 'ParameterState'],
        visualization_states: Dict[str, 'VisualizationState']
    ) -> None:
        """Render vertical stack layout.
        
        Args:
            parameter_states: Dictionary of parameter states by name
            visualization_states: Dictionary of visualization states by name
        """
        all_retargeters = set(parameter_states.keys()) | set(visualization_states.keys())
        
        for name in sorted(all_retargeters):
            if imgui.collapsing_header(name, flags=imgui.TREE_NODE_DEFAULT_OPEN)[0]:
                imgui.indent()
                
                if name in parameter_states:
                    self._render_retargeter(name, True)
                elif name in visualization_states and self._render_viz_only:
                    self._render_viz_only(name)
                
                imgui.unindent()
                imgui.spacing()
    
    def render_horizontal_layout(
        self,
        parameter_states: Dict[str, 'ParameterState'],
        visualization_states: Dict[str, 'VisualizationState']
    ) -> None:
        """Render horizontal layout with columns.
        
        Args:
            parameter_states: Dictionary of parameter states by name
            visualization_states: Dictionary of visualization states by name
        """
        all_retargeters = sorted(set(parameter_states.keys()) | set(visualization_states.keys()))
        num_retargeters = len(all_retargeters)
        
        imgui.columns(num_retargeters, "retargeter_columns")
        
        for idx, name in enumerate(all_retargeters):
            if idx > 0:
                imgui.next_column()
            
            imgui.text(name)
            imgui.separator()
            imgui.begin_child(f"col_{name}", height=-1, border=True)
            
            if name in parameter_states:
                self._render_retargeter(name, True)
            elif name in visualization_states and self._render_viz_only:
                self._render_viz_only(name)
            
            imgui.end_child()
        
        imgui.columns(1)
    
    def render_floating_layout(
        self,
        parameter_states: Dict[str, 'ParameterState'],
        window: any
    ) -> None:
        """Render free-floating ImGui windows for each retargeter.
        
        Args:
            parameter_states: Dictionary of parameter states by name
            window: GLFW window handle
        """
        window_width, window_height = glfw.get_window_size(window)
        num_windows = len(parameter_states)
        
        # Calculate grid layout for snap-to-fit
        if self._floating_auto_arrange and num_windows > 0:
            # Determine grid dimensions
            cols = int(np.ceil(np.sqrt(num_windows)))
            rows = int(np.ceil(num_windows / cols))
            
            # Calculate window size to fit in grid
            margin = 10
            controls_height = 140  # Reserve space for global controls
            available_width = window_width - margin * (cols + 1)
            available_height = window_height - controls_height - margin * (rows + 1)
            
            win_width = available_width // cols
            win_height = available_height // rows
        
        # Each retargeter gets its own movable/resizable ImGui window
        for idx, name in enumerate(parameter_states.keys()):
            # Position windows
            if self._floating_auto_arrange and num_windows > 0:
                # Grid layout
                col = idx % cols
                row = idx // cols
                x = margin + col * (win_width + margin)
                y = controls_height + margin + row * (win_height + margin)
                imgui.set_next_window_position(x, y)
                imgui.set_next_window_size(win_width, win_height)
            elif not self._floating_windows_positioned:
                # Cascade on first render
                imgui.set_next_window_position(100 + idx * 30, 100 + idx * 30, imgui.FIRST_USE_EVER)
                imgui.set_next_window_size(400, 500, imgui.FIRST_USE_EVER)
            
            # Create independent floating window
            expanded, _ = imgui.begin(f"{name}##floating", closable=False)
            if expanded:
                self._render_retargeter(name, False)
            imgui.end()
        
        # Mark as positioned after first frame
        self._floating_windows_positioned = True
        # Clear auto-arrange flag after applying
        self._floating_auto_arrange = False

