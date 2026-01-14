#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Simple Visualization Benchmark

Compares performance of:
1. 1000 individual sphere nodes (flat hierarchy)
2. 1000 spheres in a single SphereList node (batched)
3. 1000 spheres with nested transforms (3 transforms per sphere)
4. 300 chained transforms with 1000 SphereList at the end

All spheres bounce randomly inside a unit cube centered at origin.
"""

import time
import numpy as np

from teleopcore.retargeting_engine.interface import (
    BaseRetargeter,
    TensorGroupType,
    VisualizationState,
    RenderSpaceSpec,
    GraphSpec,
    SphereNodeSpec,
    SphereData,
    SphereListNodeSpec,
    SphereListData,
    TransformNodeSpec,
    TransformData,
    TextNodeSpec,
    TextData,
)
from teleopcore.retargeting_engine_ui import MultiRetargeterTuningUIImGui, LayoutModeImGui
from teleopcore.retargeting_engine.tensor_types import FloatType

# =============================================================================
# Configuration
# =============================================================================
NUM_SPHERES = 1000
CUBE_SIZE = 0.5  # Half-size of the bounding cube
SPHERE_SIZE = 0.01  # Radius in world units
SPEED = 0.5  # Movement speed
CHAIN_DEPTH = 300  # Depth for chained transforms benchmark


class SphereBenchmark(BaseRetargeter):
    """Benchmark with spheres bouncing inside a cube.
    
    Args:
        name: Retargeter name
        mode: "individual", "list", "nested", or "chain"
    """
    
    def __init__(self, name: str, mode: str = "individual"):
        self.num_spheres = NUM_SPHERES
        self.mode = mode
        
        # Initialize positions and velocities
        self.positions = np.random.uniform(-CUBE_SIZE, CUBE_SIZE, (self.num_spheres, 3))
        self.velocities = np.random.uniform(-1, 1, (self.num_spheres, 3))
        self.velocities /= np.linalg.norm(self.velocities, axis=1, keepdims=True)
        self.velocities *= SPEED
        
        # For chain mode, also need transform offsets
        if mode == "chain":
            self.chain_offsets = np.zeros((CHAIN_DEPTH, 3), dtype=np.float32)
        
        # Random colors
        self.colors = np.random.rand(self.num_spheres, 3) * 0.7 + 0.3
        
        # Timing
        self.time = 0.0
        self.dt = 0.016
        self.fps = 60.0
        self.compute_time_ms = 0.0
        
        # Create node specs based on mode
        if mode == "list":
            node_specs = self._create_list_nodes()
        elif mode == "nested":
            node_specs = self._create_nested_nodes()
        elif mode == "chain":
            node_specs = self._create_chain_nodes()
        else:
            node_specs = self._create_individual_nodes()
        
        # Create graphs
        graph_specs = [
            GraphSpec(
                "fps", "Frames Per Second", "Time (s)", "FPS",
                sample_fn=lambda: (self.time, self.fps),
                ylim=(0.0, 200.0)
            ),
        ]
        
        # Create visualization state
        mode_names = {
            "individual": "Individual Nodes",
            "list": "SphereList",
            "nested": "Nested Transforms",
            "chain": f"Chain({CHAIN_DEPTH})+List"
        }
        mode_str = mode_names.get(mode, mode)
        render_spec = RenderSpaceSpec(
            "main",
            node_specs=node_specs,
            title=f"{self.num_spheres} {mode_str}"
        )
        
        viz_state = VisualizationState(
            name,
            render_space_specs=[render_spec],
            graph_specs=graph_specs
        )
        
        super().__init__(name, visualization_state=viz_state)
    
    def _create_individual_nodes(self):
        """Create individual sphere nodes."""
        nodes = []
        
        for i in range(self.num_spheres):
            idx = i
            color = tuple(self.colors[i])
            
            node = SphereNodeSpec(
                f"sphere_{i}",
                initial_data=SphereData(
                    position=self.positions[i].copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=SPHERE_SIZE,
                    color=color
                ),
                update_fn=lambda data, idx=idx: self._update_sphere(data, idx)
            )
            nodes.append(node)
        
        nodes.append(self._create_perf_text())
        return nodes
    
    def _create_list_nodes(self):
        """Create single SphereList node with all spheres."""
        sphere_list = SphereListNodeSpec(
            "sphere_list",
            initial_data=SphereListData(
                position=np.array([0.0, 0.0, 0.0]),
                orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                visible=True,
                count=self.num_spheres,
                item_positions=self.positions.copy(),
                item_orientations=np.tile([0.0, 0.0, 0.0, 1.0], (self.num_spheres, 1)),
                sizes=np.ones(self.num_spheres) * SPHERE_SIZE,
                colors=self.colors.copy(),
            ),
            update_fn=self._update_sphere_list
        )
        return [sphere_list, self._create_perf_text()]
    
    def _create_nested_nodes(self):
        """Create 1000 parallel chains of transforms with spheres.
        
        Structure (1000 parallel chains):
        - transform_root_i → transform_l1_i → transform_l2_i → sphere_i
        
        Each intermediate transform applies an offset that gets reversed,
        so the final sphere position is correct. All transforms update every
        frame for performance testing.
        
        Total nodes: 4000 (1000 roots + 1000 L1 + 1000 L2 + 1000 spheres)
        """
        root_nodes = []
        
        for i in range(self.num_spheres):
            idx = i
            
            # Leaf: sphere at origin (transforms provide the actual position)
            sphere = SphereNodeSpec(
                f"sphere_{idx}",
                initial_data=SphereData(
                    position=np.array([0.0, 0.0, 0.0]),  # At local origin
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=SPHERE_SIZE,  # World-space size (consistent with other modes)
                    color=tuple(self.colors[idx])
                ),
                update_fn=lambda data: None,  # Static local position
            )
            
            # Level 2 transform: applies +position (sphere ends up here)
            transform_l2 = TransformNodeSpec(
                f"transform_l2_{idx}",
                initial_data=TransformData(
                    position=self.positions[idx].copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                ),
                update_fn=lambda data, idx=idx: self._update_transform_positive(data, idx),
                children=[sphere]
            )
            
            # Level 1 transform: applies -position (cancels level 2 partially for testing)
            # But we immediately re-add it in L2, so net effect is correct position
            transform_l1 = TransformNodeSpec(
                f"transform_l1_{idx}",
                initial_data=TransformData(
                    position=-self.positions[idx].copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                ),
                update_fn=lambda data, idx=idx: self._update_transform_negative(data, idx),
                children=[transform_l2]
            )
            
            # Root transform: applies +position again
            transform_root = TransformNodeSpec(
                f"transform_root_{idx}",
                initial_data=TransformData(
                    position=self.positions[idx].copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                ),
                update_fn=lambda data, idx=idx: self._update_transform_positive(data, idx),
                children=[transform_l1]
            )
            root_nodes.append(transform_root)
        
        root_nodes.append(self._create_perf_text())
        return root_nodes
    
    def _update_transform_positive(self, data: TransformData, idx: int) -> None:
        """Update transform with +position offset."""
        data.position[:] = self.positions[idx]
    
    def _update_transform_negative(self, data: TransformData, idx: int) -> None:
        """Update transform with -position offset."""
        data.position[:] = -self.positions[idx]
    
    def _create_chain_nodes(self):
        """Create 300 chained transforms with SphereList at the end.
        
        Structure:
        - transform_0 → transform_1 → ... → transform_299 → sphere_list
        
        Each transform applies a small oscillating offset (updates every frame).
        The SphereList at the end has 1000 spheres.
        
        Total nodes: 301 (300 transforms + 1 sphere_list)
        """
        import sys
        # Increase recursion limit for hierarchy flattening
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, CHAIN_DEPTH + 100))
        
        # Create the SphereList leaf node
        sphere_list = SphereListNodeSpec(
            "sphere_list",
            initial_data=SphereListData(
                position=np.array([0.0, 0.0, 0.0]),
                orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                visible=True,
                count=self.num_spheres,
                item_positions=self.positions.copy(),
                item_orientations=np.tile([0.0, 0.0, 0.0, 1.0], (self.num_spheres, 1)),
                sizes=np.ones(self.num_spheres) * SPHERE_SIZE,
                colors=self.colors.copy(),
            ),
            update_fn=self._update_sphere_list
        )
        
        # Build chain from leaf back to root
        current_node = sphere_list
        for i in range(CHAIN_DEPTH - 1, -1, -1):
            idx = i
            current_node = TransformNodeSpec(
                f"transform_{i}",
                initial_data=TransformData(
                    position=np.array([0.0, 0.0, 0.0]),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                ),
                update_fn=lambda data, idx=idx: self._update_chain_transform(data, idx),
                children=[current_node]
            )
        
        return [current_node, self._create_perf_text()]
    
    def _update_chain_transform(self, data: TransformData, idx: int) -> None:
        """Update chain transform with small oscillating offset."""
        # Small oscillation based on time and index
        offset = 0.001 * np.sin(self.time * 2.0 + idx * 0.1)
        data.position[0] = offset
        data.position[1] = offset
        data.position[2] = offset
    
    def _create_perf_text(self):
        """Create performance text node."""
        return TextNodeSpec(
            "perf_stats",
            initial_data=TextData(
                position=np.array([0.6, 0.4, 0.0]),
                orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                visible=True,
                text="",
                color=(1.0, 1.0, 0.0)
            ),
            update_fn=self._update_perf_text
        )
    
    def _update_sphere(self, data: SphereData, idx: int) -> None:
        """Update a single sphere position."""
        data.position[:] = self.positions[idx]
    
    def _update_sphere_list(self, data: SphereListData) -> None:
        """Update all sphere positions at once."""
        data.item_positions[:] = self.positions
    
    def _update_perf_text(self, data: TextData) -> None:
        """Update performance stats text."""
        mode_names = {
            "individual": "Individual Nodes",
            "list": "SphereList",
            "nested": "Nested Transforms",
            "chain": f"Chain({CHAIN_DEPTH})+List"
        }
        mode_str = mode_names.get(self.mode, self.mode)
        data.text = (
            f"{mode_str}\n"
            f"Spheres: {self.num_spheres}\n"
            f"FPS: {self.fps:.1f}\n"
            f"Compute: {self.compute_time_ms:.2f}ms"
        )
    
    def input_spec(self):
        return {}
    
    def output_spec(self):
        return {"dummy": TensorGroupType("dummy", [FloatType("x")])}
    
    def compute(self, inputs, outputs):
        """Update sphere positions - bounce inside cube."""
        t0 = time.perf_counter()
        
        # Update positions
        self.positions += self.velocities * self.dt
        
        # Bounce off walls
        bound = CUBE_SIZE
        for axis in range(3):
            mask_low = self.positions[:, axis] < -bound
            mask_high = self.positions[:, axis] > bound
            self.velocities[mask_low, axis] = abs(self.velocities[mask_low, axis])
            self.velocities[mask_high, axis] = -abs(self.velocities[mask_high, axis])
            self.positions[:, axis] = np.clip(self.positions[:, axis], -bound, bound)
        
        self.time += self.dt
        outputs["dummy"][0] = 0.0
        
        t1 = time.perf_counter()
        self.compute_time_ms = (t1 - t0) * 1000.0


def run_benchmark(name: str, mode: str, duration: float = 10.0) -> dict:
    """Run a single benchmark and return results."""
    print(f"\n{'='*60}")
    print(f"Running: {name}")
    print(f"{'='*60}")
    
    benchmark = SphereBenchmark(name, mode=mode)
    print(f"  Created {benchmark.num_spheres} spheres (mode={mode})")
    
    with MultiRetargeterTuningUIImGui(
        [benchmark],
        title=name,
        layout_mode=LayoutModeImGui.HORIZONTAL
    ) as ui:
        print(f"  UI started - running for {duration}s...")
        
        frame = 0
        start_time = time.time()
        fps_samples = []
        target_frame_time = 1.0 / 60.0  # 60 FPS target
        last_frame_start = time.perf_counter()
        
        try:
            while time.time() - start_time < duration:
                if not ui.is_running():
                    break
                
                frame_start = time.perf_counter()
                
                # Do the work
                benchmark({})
                frame += 1
                
                work_time = time.perf_counter() - frame_start
                
                # Compute FPS as inverse of work time (not including sleep)
                if work_time > 0:
                    benchmark.fps = 1.0 / work_time
                    fps_samples.append(benchmark.fps)
                
                # Sleep remaining time to hit 60 FPS target
                remaining = target_frame_time - work_time
                if remaining > 0:
                    time.sleep(remaining)
                
        except KeyboardInterrupt:
            print("  Interrupted by user")
        
        elapsed = time.time() - start_time
        avg_fps = sum(fps_samples) / len(fps_samples) if fps_samples else 0
    
    print(f"  Duration: {elapsed:.1f}s, Frames: {frame}, Avg FPS: {avg_fps:.1f}")
    return {"name": name, "duration": elapsed, "frames": frame, "avg_fps": avg_fps}


def main():
    """Run all benchmarks and compare results."""
    print("=" * 60)
    print("Visualization Benchmark")
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  - Spheres: {NUM_SPHERES}")
    print(f"  - Cube size: {CUBE_SIZE * 2}m")
    print(f"  - Sphere size: {SPHERE_SIZE}m")
    print(f"  - Chain depth: {CHAIN_DEPTH}")
    
    duration = 30.0
    
    result1 = run_benchmark("Individual Nodes", mode="individual", duration=duration)
    result2 = run_benchmark("SphereList", mode="list", duration=duration)
    result3 = run_benchmark("Nested Transforms", mode="nested", duration=duration)
    result4 = run_benchmark(f"Chain({CHAIN_DEPTH})+List", mode="chain", duration=duration)
    
    # Print comparison
    print("\n" + "=" * 60)
    print("Results Comparison")
    print("=" * 60)
    print(f"\n{'Method':<25} {'Avg FPS':>10} {'Speedup':>10}")
    print("-" * 45)
    
    baseline_fps = result1['avg_fps']
    
    def print_result(name, result):
        if baseline_fps > 0:
            speedup = result['avg_fps'] / baseline_fps
            print(f"{name:<25} {result['avg_fps']:>10.1f} {speedup:>9.1f}x")
        else:
            print(f"{name:<25} {result['avg_fps']:>10.1f} {'N/A':>10}")
    
    print_result("Individual Nodes", result1)
    print_result("SphereList", result2)
    print_result("Nested Transforms", result3)
    print_result(f"Chain({CHAIN_DEPTH})+List", result4)
    
    print("\n" + "=" * 60)
    print("Benchmark complete!")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
