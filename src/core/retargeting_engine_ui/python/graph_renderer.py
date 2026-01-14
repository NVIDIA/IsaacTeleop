# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Graph/plot renderer using ImGui.

Provides rendering for:
- Time-series line plots
- Real-time data visualization
- Multiple graphs in a single panel
"""

from typing import Dict, Optional

import numpy as np
import imgui  # type: ignore[import-not-found]


class GraphRenderer:
    """Renders graphs and plots using ImGui.
    
    Handles:
    - Line plot rendering
    - Auto-scaling Y axis
    - Latest value display
    """
    
    def __init__(self, default_height: float = 150.0):
        """Initialize graph renderer.
        
        Args:
            default_height: Default height for graph plots in pixels
        """
        self._default_height = default_height
    
    def render_graph(
        self,
        graph: dict,
        unique_suffix: str = "",
        height: Optional[float] = None
    ) -> None:
        """Render a single graph.
        
        Args:
            graph: Graph data dictionary with keys:
                - name: Graph identifier
                - title: Display title
                - x_data: List of X values
                - y_data: List of Y values
                - ylim: Optional tuple of (y_min, y_max)
            unique_suffix: Suffix to make widget IDs unique
            height: Optional graph height (defaults to _default_height)
        """
        imgui.text(graph['title'])
        
        if graph['x_data'] and graph['y_data']:
            imgui.same_line()
            imgui.text(f"  Latest: ({graph['x_data'][-1]:.3f}, {graph['y_data'][-1]:.3f})")
            
            y_array = np.array(graph['y_data'], dtype=np.float32)
            
            if graph['ylim']:
                y_min, y_max = graph['ylim']
            else:
                y_min = float(np.min(y_array))
                y_max = float(np.max(y_array))
                margin = (y_max - y_min) * 0.1 if y_max > y_min else 1.0
                y_min -= margin
                y_max += margin
            
            graph_height = height if height is not None else self._default_height
            imgui.plot_lines(
                f"##{graph['name']}{unique_suffix}",
                y_array,
                scale_min=y_min,
                scale_max=y_max,
                graph_size=(imgui.get_content_region_available()[0], graph_height)
            )
        else:
            imgui.same_line()
            imgui.text("  No data")
    
    def render_single_graph(
        self,
        graph: dict,
        unique_suffix: str = "",
        height: Optional[float] = None
    ) -> None:
        """Render a single graph (alias for render_graph for clarity).
        
        Args:
            graph: Graph data dictionary
            unique_suffix: Suffix to make widget IDs unique
            height: Optional graph height
        """
        self.render_graph(graph, unique_suffix, height)
    
    def render_graphs_inline(
        self,
        graphs: Dict[str, dict],
        unique_suffix: str = ""
    ) -> None:
        """Render multiple graphs inline (within current window).
        
        Args:
            graphs: Dictionary of graph data
            unique_suffix: Suffix to make widget IDs unique
        """
        if not graphs:
            return
        
        for graph in graphs.values():
            self.render_graph(graph, unique_suffix)
            imgui.spacing()
    
    def render_graphs_window(
        self,
        name: str,
        graphs: Dict[str, dict]
    ) -> None:
        """Render all graphs in a separate floating window.
        
        Args:
            name: Retargeter name for window title
            graphs: Dictionary of graph data
        """
        if not graphs:
            return
        
        imgui.begin(f"{name} - Graphs", True, imgui.WINDOW_NO_COLLAPSE)
        
        for graph in graphs.values():
            self.render_graph(graph)
            imgui.separator()
        
        imgui.end()

