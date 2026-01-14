#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Simple visualization example showing chained position dampening/smoothing.

Demonstrates:
- A source that generates a jumping position (changes every second)
- Two chained dampeners that progressively smooth the position
- Visualization of input and output positions for each dampener
- Graphs of velocity magnitude and tracking offset over time
"""

import time
import numpy as np

from teleopcore.retargeting_engine.interface import (
    BaseRetargeter,
    VisualizationState,
    ParameterState,
    FloatParameter,
    BoolParameter,
    MarkerNodeSpec,
    ArrowNodeSpec,
    LineNodeSpec,
    TextNodeSpec,
    MarkerData,
    ArrowData,
    LineData,
    TextData,
    RenderSpaceSpec,
    GraphSpec,
    TensorGroupType,
)
from teleopcore.retargeting_engine_ui import MultiRetargeterTuningUIImGui, LayoutModeImGui
from teleopcore.retargeting_engine.tensor_types import FloatType


class JumpingPositionSource(BaseRetargeter):
    """
    Source that generates a position that randomly jumps every second.
    
    Simulates noisy/jumpy input data like raw tracking data.
    """
    
    def __init__(self, name: str = "JumpingSource"):
        self.time = 0.0
        self.last_jump_time = 0.0
        self.jump_interval = 1.0  # Jump every second
        
        # Current target position (jumps randomly)
        self.target_pos = np.array([0.0, 0.0, 0.5])
        
        # No parameters or visualization needed for source
        super().__init__(name)
        
    def input_spec(self):
        """No inputs - this is a source."""
        return {}
        
    def output_spec(self):
        """Output: raw_position (x, y, z)"""
        return {
            "raw_position": TensorGroupType("raw_position", [
                FloatType("x"),
                FloatType("y"),
                FloatType("z"),
            ])
        }
        
    def compute(self, inputs, outputs):
        """Generate jumping position."""
        self.time += 0.016
        
        # Jump to new random position every second
        if self.time - self.last_jump_time >= self.jump_interval:
            self.target_pos = np.array([
                np.random.uniform(-0.8, 0.8),
                np.random.uniform(-0.8, 0.8),
                np.random.uniform(0.0, 1.0),
            ])
            self.last_jump_time = self.time
        
        # Output current position
        outputs["raw_position"][0] = float(self.target_pos[0])
        outputs["raw_position"][1] = float(self.target_pos[1])
        outputs["raw_position"][2] = float(self.target_pos[2])


class PositionDampener(BaseRetargeter):
    """
    Retargeter that smooths/dampens a position using exponential smoothing.
    
    Uses exponential smoothing to create a smooth output from noisy input.
    Visualizes both input and output positions with hierarchical nodes.
    
    Demonstrates:
    - Parent-child node relationships for visualization
    - Dynamic visibility toggling
    - Real-time graphs
    """
    
    def __init__(
        self,
        name: str = "PositionDampener",
        damping_factor: float = 0.1,
        output_color: tuple = (0.2, 1.0, 0.2),
        input_color: tuple = (1.0, 0.3, 0.3),
    ):
        # Dampening state
        self.time = 0.0
        self.damping_factor = damping_factor  # Lower = more smoothing
        self._output_color = output_color
        self._input_color = input_color
        
        # Tunable parameters
        self.show_velocity_arrow = True
        self.show_connection_line = True
        
        # Positions
        self.input_pos = np.array([0.0, 0.0, 0.5])
        self.output_pos = np.array([0.0, 0.0, 0.5])
        self.prev_output_pos = np.array([0.0, 0.0, 0.5])
        
        # Relative offset from output to input (for visualization)
        self.offset_to_input = np.array([0.0, 0.0, 0.0])
        
        # Velocity (for visualization and graph)
        self.velocity = np.array([0.0, 0.0, 0.0])
        self.velocity_magnitude = 0.0
        
        # Create visualization nodes using clean update methods
        node_specs = [
            # Output position (dampened) - MarkerNode for screen-space size
            MarkerNodeSpec(
                "output",
                initial_data=MarkerData(
                    position=np.array([0.0, 0.0, 0.5]),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=15.0,  # 15px screen-space radius
                    color=self._output_color,
                ),
                update_fn=self._update_output_marker,
                children=[
                    TextNodeSpec(
                        "output_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.05]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=self._update_output_label,
                    ),
                ],
            ),
            
            # Input position - MarkerNode for screen-space size
            MarkerNodeSpec(
                "input",
                initial_data=MarkerData(
                    position=np.array([0.0, 0.0, 0.5]),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=10.0,  # 10px screen-space radius
                    color=self._input_color,
                ),
                update_fn=self._update_input_marker,
                children=[
                    TextNodeSpec(
                        "input_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.05]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=self._update_input_label,
                    ),
                ],
            ),
            
            # Velocity arrow - visibility controlled by parameter
            ArrowNodeSpec(
                "velocity_arrow",
                initial_data=ArrowData(
                    position=np.array([0.0, 0.0, 0.5]),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    length=0.1,  # 10cm initial length (updated dynamically)
                    width=2.0,
                    color=self._output_color
                ),
                update_fn=self._update_velocity_arrow,
            ),
            
            # Connection line - visibility controlled by parameter
            LineNodeSpec(
                "error_line",
                initial_data=LineData(
                    position=np.array([0.0, 0.0, 0.5]),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    end_point=np.array([0.0, 0.0, 0.0]),
                    width=1.0,
                    color=(1.0, 1.0, 0.0)
                ),
                update_fn=self._update_connection_line,
            ),
        ]
        
        graph_specs = [
            GraphSpec(
                "velocity",
                "Output Velocity Magnitude",
                "Time (s)",
                "Speed (m/s)",
                sample_fn=lambda: (self.time, self.velocity_magnitude),
                ylim=(0.0, 5.0)
            ),
            GraphSpec(
                "offset",
                "Input-Output Offset",
                "Time (s)",
                "Distance (m)",
                sample_fn=lambda: (self.time, np.linalg.norm(self.offset_to_input)),
                ylim=(0.0, 2.0)
            )
        ]
        
        # Create parameter state for tunable parameters
        parameters = [
            FloatParameter(
                name="damping_factor",
                description="Damping factor (lower = smoother)",
                min_value=0.01,
                max_value=1.0,
                default_value=0.1,
                sync_fn=lambda v: setattr(self, 'damping_factor', v)
            ),
            BoolParameter(
                name="show_velocity_arrow",
                description="Show velocity arrow",
                default_value=True,
                sync_fn=lambda v: setattr(self, 'show_velocity_arrow', v)
            ),
            BoolParameter(
                name="show_connection_line",
                description="Show connection line",
                default_value=True,
                sync_fn=lambda v: setattr(self, 'show_connection_line', v)
            ),
        ]
        
        param_state = ParameterState(
            name=name,
            parameters=parameters,
            config_file=f"{name.lower().replace(' ', '_')}_config.json"
        )
        
        viz_state = VisualizationState(
            name,
            render_space_specs=[
                RenderSpaceSpec("main", "3D View", node_specs=node_specs)
            ],
            graph_specs=graph_specs
        )
        super().__init__(name, parameter_state=param_state, visualization_state=viz_state)
    
    def _update_output_marker(self, data: MarkerData) -> None:
        """Update output marker position."""
        data.position[:] = self.output_pos
    
    def _update_output_label(self, data: TextData) -> None:
        """Update output label text."""
        data.text = f"Output\n{self.velocity_magnitude:.2f} m/s\nDamping: {self.damping_factor:.3f}"
    
    def _update_input_marker(self, data: MarkerData) -> None:
        """Update input marker position."""
        data.position[:] = self.input_pos
    
    def _update_input_label(self, data: TextData) -> None:
        """Update input label text."""
        data.text = f"Input\nOffset: {np.linalg.norm(self.offset_to_input):.2f}m"
    
    def _update_connection_line(self, data: LineData) -> None:
        """Update connection line between input and output."""
        data.position[:] = self.output_pos
        data.visible = self.show_connection_line
        data.end_point[:] = self.input_pos - self.output_pos
    
    def _update_velocity_arrow(self, data: ArrowData) -> None:
        """Update velocity arrow data in-place."""
        # Update position
        data.position[:] = self.output_pos
        
        # Update visibility
        data.visible = self.show_velocity_arrow
        
        # Update length - scale velocity to reasonable arrow size
        # Velocity of 1 m/s -> 0.3m arrow (30cm), minimum 5cm
        data.length = max(0.05, np.linalg.norm(self.velocity) * 0.3)
        
        # Compute orientation from velocity vector
        vel = self.velocity
        vel_norm = np.linalg.norm(vel)
        if vel_norm < 1e-6:
            data.orientation[:] = [0.0, 0.0, 0.0, 1.0]  # Identity if no velocity
            return
        
        direction = vel / vel_norm
        
        # Rotate +Z axis to point along direction
        z_axis = np.array([0.0, 0.0, 1.0])
        dot = np.dot(z_axis, direction)
        
        if dot > 0.999999:
            data.orientation[:] = [0.0, 0.0, 0.0, 1.0]
        elif dot < -0.999999:
            data.orientation[:] = [1.0, 0.0, 0.0, 0.0]
        else:
            axis = np.cross(z_axis, direction)
            axis = axis / np.linalg.norm(axis)
            angle = np.arccos(dot)
            half_angle = angle * 0.5
            s = np.sin(half_angle)
            data.orientation[:] = [axis[0] * s, axis[1] * s, axis[2] * s, np.cos(half_angle)]
    
    def input_spec(self):
        """Input: position (x, y, z)"""
        return {
            "position": TensorGroupType("position", [
                FloatType("x"),
                FloatType("y"),
                FloatType("z"),
            ])
        }
        
    def output_spec(self):
        """Output: position (x, y, z)"""
        return {
            "position": TensorGroupType("position", [
                FloatType("x"),
                FloatType("y"),
                FloatType("z"),
            ])
        }
        
    def compute(self, inputs, outputs):
        """Apply exponential smoothing to the position."""
        self.time += 0.016
        
        # Get input position
        self.input_pos = np.array([
            inputs["position"][0],
            inputs["position"][1],
            inputs["position"][2],
        ])
        
        # Apply exponential smoothing: output = output + damping_factor * (input - output)
        self.prev_output_pos = self.output_pos.copy()
        self.output_pos = self.output_pos + self.damping_factor * (self.input_pos - self.output_pos)
        
        # Calculate offset from output to input (for visualization)
        self.offset_to_input = self.input_pos - self.output_pos
        
        # Calculate velocity (change in output position)
        dt = 0.016
        self.velocity = (self.output_pos - self.prev_output_pos) / dt
        self.velocity_magnitude = np.linalg.norm(self.velocity)
        
        # Output position
        outputs["position"][0] = float(self.output_pos[0])
        outputs["position"][1] = float(self.output_pos[1])
        outputs["position"][2] = float(self.output_pos[2])


def main():
    """Run chained dampener visualization example."""
    import sys
    
    # Parse layout mode from command line
    layout_mode = LayoutModeImGui.TABS
    if len(sys.argv) > 1:
        mode_str = sys.argv[1].lower()
        mode_map = {
            "tabs": LayoutModeImGui.TABS,
            "vertical": LayoutModeImGui.VERTICAL,
            "horizontal": LayoutModeImGui.HORIZONTAL,
            "floating": LayoutModeImGui.FLOATING,
        }
        layout_mode = mode_map.get(mode_str, LayoutModeImGui.TABS)
    
    print("\n" + "=" * 60)
    print("Chained Dampener Visualization Demo")
    print("=" * 60)
    print(f"Layout mode: {layout_mode.value}")
    print("Usage: python simple_visualization_demo.py [tabs|vertical|horizontal|floating]")
    
    print("\n[1/4] Creating source (jumping position)...")
    source = JumpingPositionSource("JumpingSource")
    print("✓ Source created")
    
    print("\n[2/4] Creating first dampener (fast response)...")
    dampener1 = PositionDampener(
        "Dampener 1 (Fast)",
        damping_factor=0.3,
        output_color=(0.2, 0.8, 1.0),  # Cyan
        input_color=(1.0, 0.3, 0.3),   # Red
    )
    print("✓ Dampener 1 created (damping=0.3)")
    
    print("\n[3/4] Creating second dampener (slow/smooth)...")
    dampener2 = PositionDampener(
        "Dampener 2 (Smooth)",
        damping_factor=0.1,
        output_color=(0.2, 1.0, 0.2),  # Green
        input_color=(0.2, 0.8, 1.0),   # Cyan (matches dampener1 output)
    )
    print("✓ Dampener 2 created (damping=0.1)")
    
    print("\n[4/4] Starting unified UI (2 dampeners)...")
    with MultiRetargeterTuningUIImGui(
        [dampener1, dampener2],
        title="Chained Dampener Demo",
        layout_mode=layout_mode
    ) as ui:
        print("✓ Unified UI started")
        print("  - Pipeline: Source → Dampener 1 → Dampener 2")
        print("  - Dampener 1: Fast response (cyan), tracks jumping source (red)")
        print("  - Dampener 2: Smooth output (green), tracks dampener 1 (cyan)")
        print("  - Layout: " + layout_mode.value)
        
        print("\nRunning simulation...")
        print("  - Adjust damping factors to see chained effect")
        print("  - Toggle visibility of arrows/lines per dampener")
        print("  - Close window or press Ctrl+C to exit")
        
        frame = 0
        start_time = time.time()
        
        try:
            while ui.is_running():
                # Pipeline: Source → Dampener 1 → Dampener 2
                raw_output = source({})
                damp1_output = dampener1({"position": raw_output["raw_position"]})
                damp2_output = dampener2({"position": damp1_output["position"]})
                
                if frame % 180 == 0:
                    elapsed = time.time() - start_time
                    fps = frame / elapsed if elapsed > 0 else 0
                    print(f"  [{elapsed:.1f}s] Frame {frame} - FPS: {fps:.1f}")
                
                frame += 1
                time.sleep(0.016)
                    
        except KeyboardInterrupt:
            print("\n  Interrupted by user")
        
        elapsed = time.time() - start_time
        fps = frame / elapsed if elapsed > 0 else 0
        print(f"\n✓ Simulation complete ({elapsed:.1f}s, {frame} frames, {fps:.1f} FPS)")
    
    print("\n✅ Example completed!")


if __name__ == "__main__":
    main()
