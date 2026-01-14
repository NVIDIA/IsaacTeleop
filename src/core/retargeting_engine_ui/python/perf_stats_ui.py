# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Performance statistics UI using ImGui.

Provides rendering for:
- Compute time breakdown
- Parameter sync overhead
- Visualization update overhead
- Frame rate and frame count
"""

from typing import TYPE_CHECKING, Dict

import imgui  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from teleopcore.retargeting_engine.interface import RetargeterStats


class PerfStatsRenderer:
    """Renders performance statistics for retargeters.
    
    Displays:
    - Compute time in milliseconds
    - Parameter sync overhead
    - Visualization update overhead
    - Total time and FPS
    - Frame count
    """
    
    def __init__(self):
        """Initialize performance stats renderer."""
        pass
    
    def render_stats(
        self,
        stats: 'RetargeterStats',
        show_header: bool = True,
        name: str = ""
    ) -> None:
        """Render performance statistics.
        
        Args:
            stats: RetargeterStats object to render
            show_header: Whether to show collapsible "Performance" header
            name: Unique name for widget IDs (to avoid ID conflicts)
        """
        # Collapsible section - skip rendering if collapsed
        if show_header:
            imgui.spacing()
            expanded, _ = imgui.collapsing_header(f"Performance##{name}")
            if not expanded:
                return
            imgui.indent()
        
        snapshot = stats.get_snapshot()
        compute_ms = snapshot['compute_ms']
        param_ms = snapshot['param_sync_ms']
        viz_ms = snapshot['viz_update_ms']
        total_ms = snapshot['total_ms']
        fps = snapshot['fps']
        frame_count = snapshot['frame_count']
        
        # Compute time
        imgui.text(f"Compute:     {compute_ms:6.3f} ms")
        if total_ms > 0:
            imgui.same_line(200)
            compute_pct = (compute_ms / total_ms) * 100
            imgui.text(f"({compute_pct:5.1f}%)")
        
        # Parameter sync overhead
        if param_ms > 0.001:  # Only show if non-negligible
            imgui.text(f"Param Sync:  {param_ms:6.3f} ms")
            if total_ms > 0:
                imgui.same_line(200)
                param_pct = (param_ms / total_ms) * 100
                imgui.text(f"({param_pct:5.1f}%)")
        
        # Visualization update overhead
        if viz_ms > 0.001:  # Only show if non-negligible
            imgui.text(f"Viz Update:  {viz_ms:6.3f} ms")
            if total_ms > 0:
                imgui.same_line(200)
                viz_pct = (viz_ms / total_ms) * 100
                imgui.text(f"({viz_pct:5.1f}%)")
        
        # Total
        imgui.separator()
        imgui.text(f"Total:       {total_ms:6.3f} ms")
        if total_ms > 0:
            imgui.same_line(200)
            imgui.text(f"({fps:5.1f} Hz)")
        
        # Frame count
        imgui.text(f"Frames:      {frame_count}")
        
        if show_header:
            imgui.unindent()
    
    def render_stats_from_dict(
        self,
        name: str,
        stats_dict: Dict[str, 'RetargeterStats']
    ) -> None:
        """Render stats for a named retargeter from a dictionary.
        
        Args:
            name: Name of the retargeter
            stats_dict: Dictionary mapping names to RetargeterStats objects
        """
        if name not in stats_dict:
            return
        
        self.render_stats(stats_dict[name])

