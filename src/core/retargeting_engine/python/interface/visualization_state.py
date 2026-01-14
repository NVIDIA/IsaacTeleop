# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Visualization state management for retargeting systems.

Provides a state container that retargeters write to, and a UI that renders from.
Mirrors the parameter_state.py design but in reverse: data flows OUT of the retargeter.
"""

from typing import Dict, List, Tuple, Callable, Optional
import threading

import numpy as np

# Import node specs and utilities from dedicated module
from .node_specs import (
    Node3D,
    NodeSpec,
    TransformNodeSpec,
    SphereNodeSpec,
    MarkerNodeSpec,
    ArrowNodeSpec,
    LineNodeSpec,
    TextNodeSpec,
    RenderNodeData,
    compute_world_transforms,
    flatten_node_hierarchy,
)


class RenderSpaceSpec:
    """Specification for a 3D render space (viewport with camera settings and nodes).
    
    Each render space contains its own set of 3D nodes and camera configuration.
    Each NodeSpec manages its own double-buffered data.
    
    Data flow:
    - Compute thread calls sync() which updates all node specs
    - UI thread calls get_snapshot() to get rendered data with world transforms
    """
    
    def __init__(
        self,
        name: str,
        title: str = "3D View",
        node_specs: Optional[List[NodeSpec]] = None,
        projection: str = "perspective",
        camera_position: Tuple[float, float, float] = (2.0, 2.0, 2.0),
        camera_azimuth: float = 45.0,
        camera_elevation: float = -45.0,
        fov: float = 60.0,
    ):
        """
        Define a 3D render space specification.
        
        Args:
            name: Unique identifier for this render space
            title: Display title for the UI
            node_specs: List of node specifications for this render space
            projection: "perspective" or "orthographic"
            camera_position: Initial camera position (x, y, z)
            camera_azimuth: Initial horizontal rotation in degrees
            camera_elevation: Initial vertical rotation in degrees (negative = looking down)
            fov: Field of view in degrees (for perspective projection)
        """
        self.name = name
        self.title = title
        self.node_specs = node_specs if node_specs is not None else []
        self.projection = projection
        self.camera_position = camera_position
        self.camera_azimuth = camera_azimuth
        self.camera_elevation = camera_elevation
        self.fov = fov
        
        # Flatten hierarchy at init time (sets parent references)
        self._flat_specs: Dict[str, NodeSpec] = flatten_node_hierarchy(self.node_specs) if self.node_specs else {}
        
        # Pre-filter dynamic nodes (those with update_fn) for fast iteration
        self._dynamic_specs: List[NodeSpec] = [
            spec for spec in self._flat_specs.values() 
            if spec._update_fn is not None
        ]
        
        # UI can set this to skip sync when collapsed
        self.enabled = True
        
        # =====================================================================
        # Global Triple Buffer - ONE swap for ALL nodes (O(1) instead of O(n))
        # =====================================================================
        # Buffer 0, 1, 2 each contain ALL node data
        self._buffers: List[Dict[str, Node3D]] = [
            {name: spec.create_data_instance() for name, spec in self._flat_specs.items()},
            {name: spec.create_data_instance() for name, spec in self._flat_specs.items()},
            {name: spec.create_data_instance() for name, spec in self._flat_specs.items()},
        ]
        
        # Global buffer indices
        self._write_idx = 0
        self._ready_idx = 1
        self._read_idx = 2
        
        # Global dirty flag
        self._dirty = False
        
        # Single lock protects ONLY the index swaps (2 integer assignments)
        self._swap_lock = threading.Lock()
    
    def sync(self, profile: bool = False) -> None:
        """
        Update all node specs via their update lambdas. Called from compute thread.
        
        Uses global triple buffer - ONE swap for ALL nodes:
        1. Update dynamic nodes in write buffer (no lock)
        2. Swap WRITE↔READY indices (one lock, instant)
        
        Skips if enabled=False (set by UI when collapsed).
        """
        if not self.enabled or not self._dynamic_specs:
            return
        
        if profile:
            import time
            t0 = time.perf_counter()
        
        # Phase 1: Update dynamic nodes in write buffer (no lock needed)
        write_buffer = self._buffers[self._write_idx]
        for spec in self._dynamic_specs:
            spec.update(write_buffer[spec.name])
        
        if profile:
            t1 = time.perf_counter()
        
        # Phase 2: ONE swap for ALL nodes (instant - just 2 integer assignments)
        with self._swap_lock:
            self._write_idx, self._ready_idx = self._ready_idx, self._write_idx
            self._dirty = True
        
        if profile:
            t2 = time.perf_counter()
            print(f"[PROFILE] RenderSpaceSpec.sync: update={1000*(t1-t0):.3f}ms, swap={1000*(t2-t1):.3f}ms, dynamic={len(self._dynamic_specs)}/{len(self._flat_specs)}")
    
    def get_snapshot(self, profile: bool = False, hierarchical: bool = True) -> dict:
        """
        Get snapshot for rendering. Called from UI thread.
        
        Args:
            profile: If True, print timing information
            hierarchical: If True, return tree structure with local transforms (GPU handles hierarchy).
                         If False, compute world transforms in Python (legacy mode).
        """
        if profile:
            import time
            t0 = time.perf_counter()
        
        if hierarchical:
            nodes = self._build_render_nodes_hierarchical(profile=profile)
        else:
            nodes = self._build_render_nodes(profile=profile)
        
        if profile:
            t1 = time.perf_counter()
            print(f"[PROFILE] RenderSpaceSpec.get_snapshot: {1000*(t1-t0):.3f}ms")
        
        return {
            'name': self.name,
            'title': self.title,
            'projection': self.projection,
            'camera_position': self.camera_position,
            'camera_azimuth': self.camera_azimuth,
            'camera_elevation': self.camera_elevation,
            'fov': self.fov,
            'nodes': nodes,
            'node_tree': self.node_specs if hierarchical else None,  # Original tree for hierarchical rendering
        }
    
    def _build_render_nodes_hierarchical(self, profile: bool = False) -> Dict[str, dict]:
        """
        Build render node data with LOCAL transforms only (no world transform computation).
        The renderer handles the hierarchy via model matrix stack.
        Called from UI thread.
        """
        if not self._flat_specs:
            return {}
        
        # ONE swap for ALL nodes (instant)
        with self._swap_lock:
            if self._dirty:
                self._ready_idx, self._read_idx = self._read_idx, self._ready_idx
                self._dirty = False
        
        # Read from stable READ buffer
        read_buffer = self._buffers[self._read_idx]
        
        # Convert to dict format - use LOCAL transforms (no world transform computation!)
        result: Dict[str, dict] = {}
        for name, spec in self._flat_specs.items():
            data = read_buffer[name]
            node_dict = {
                'name': name,
                'type': spec.get_node_type(),
                'parent': spec.parent,
                'position': data.position,  # LOCAL transform
                'orientation': data.orientation,  # LOCAL transform
                'visible': data.visible,
            }
            
            # Add type-specific data
            if spec.get_node_type() == 'marker':
                from .node_specs import MarkerData
                if isinstance(data, MarkerData):
                    node_dict['size'] = data.size
                    node_dict['color'] = data.color
            elif spec.get_node_type() == 'arrow':
                from .node_specs import ArrowData
                if isinstance(data, ArrowData):
                    node_dict['length'] = data.length
                    node_dict['width'] = data.width
                    node_dict['color'] = data.color
            elif spec.get_node_type() == 'line':
                from .node_specs import LineData
                if isinstance(data, LineData):
                    node_dict['end_point'] = data.end_point
                    node_dict['width'] = data.width
                    node_dict['color'] = data.color
            elif spec.get_node_type() == 'text':
                from .node_specs import TextData
                if isinstance(data, TextData):
                    node_dict['text'] = data.text
                    node_dict['color'] = data.color
            elif spec.get_node_type() == 'sphere_list':
                from .node_specs import SphereListData
                if isinstance(data, SphereListData):
                    node_dict['count'] = data.count
                    node_dict['item_positions'] = data.item_positions
                    node_dict['item_orientations'] = data.item_orientations
                    node_dict['sizes'] = data.sizes
                    node_dict['colors'] = data.colors
            elif spec.get_node_type() == 'marker_list':
                from .node_specs import MarkerListData
                if isinstance(data, MarkerListData):
                    node_dict['count'] = data.count
                    node_dict['item_positions'] = data.item_positions
                    node_dict['sizes'] = data.sizes
                    node_dict['colors'] = data.colors
            elif spec.get_node_type() == 'line_list':
                from .node_specs import LineListData
                if isinstance(data, LineListData):
                    node_dict['count'] = data.count
                    node_dict['item_positions'] = data.item_positions
                    node_dict['end_points'] = data.end_points
                    node_dict['widths'] = data.widths
                    node_dict['colors'] = data.colors
            
            result[name] = node_dict
        
        return result
    
    def _build_render_nodes(self, profile: bool = False) -> Dict[str, dict]:
        """
        Build render node data from node specs and compute world transforms.
        Called from UI thread. (Legacy mode - slower but doesn't require hierarchical renderer)
        """
        if not self._flat_specs:
            return {}
        
        # ONE swap for ALL nodes (instant - just 2 integer assignments)
        with self._swap_lock:
            if self._dirty:
                self._ready_idx, self._read_idx = self._read_idx, self._ready_idx
                self._dirty = False
        
        # Read from stable READ buffer (no lock needed)
        read_buffer = self._buffers[self._read_idx]
        render_nodes: Dict[str, RenderNodeData] = {}
        for name, spec in self._flat_specs.items():
            render_nodes[name] = RenderNodeData(
                name=name,
                node_type=spec.get_node_type(),
                parent=spec.parent,
                data=read_buffer[name]  # Read from global buffer
            )
        
        # Compute world transforms (writes to render_node.world_position/orientation)
        compute_world_transforms(render_nodes, profile=profile)
        
        # Convert to dict format for UI
        result: Dict[str, dict] = {}
        for name, render_node in render_nodes.items():
            node_dict = {
                'name': name,
                'type': render_node.node_type,
                'parent': render_node.parent,
                'position': render_node.world_position,  # Use world transform
                'orientation': render_node.world_orientation,  # Use world transform
                'visible': render_node.data.visible,
            }
            
            # Add type-specific data
            data = render_node.data
            if render_node.node_type == 'marker':
                from .node_specs import MarkerData
                if isinstance(data, MarkerData):
                    node_dict['size'] = data.size
                    node_dict['color'] = data.color
            elif render_node.node_type == 'arrow':
                from .node_specs import ArrowData
                if isinstance(data, ArrowData):
                    node_dict['length'] = data.length
                    node_dict['width'] = data.width
                    node_dict['color'] = data.color
            elif render_node.node_type == 'line':
                from .node_specs import LineData
                if isinstance(data, LineData):
                    node_dict['end_point'] = data.end_point
                    node_dict['width'] = data.width
                    node_dict['color'] = data.color
            elif render_node.node_type == 'text':
                from .node_specs import TextData
                if isinstance(data, TextData):
                    node_dict['text'] = data.text
                    node_dict['color'] = data.color
            elif render_node.node_type == 'line_list':
                from .node_specs import LineListData
                if isinstance(data, LineListData):
                    # Batch type - item positions are relative to batch world transform
                    node_dict['count'] = data.count
                    node_dict['item_positions'] = data.item_positions
                    node_dict['item_orientations'] = data.item_orientations
                    node_dict['end_points'] = data.end_points
                    node_dict['widths'] = data.widths
                    node_dict['colors'] = data.colors
            elif render_node.node_type == 'marker_list':
                from .node_specs import MarkerListData
                if isinstance(data, MarkerListData):
                    # Batch type - item positions are relative to batch world transform
                    node_dict['count'] = data.count
                    node_dict['item_positions'] = data.item_positions
                    node_dict['item_orientations'] = data.item_orientations
                    node_dict['sizes'] = data.sizes
                    node_dict['colors'] = data.colors
            elif render_node.node_type == 'sphere_list':
                from .node_specs import SphereListData
                if isinstance(data, SphereListData):
                    # Batch type - world-space spheres
                    node_dict['count'] = data.count
                    node_dict['item_positions'] = data.item_positions
                    node_dict['item_orientations'] = data.item_orientations
                    node_dict['sizes'] = data.sizes
                    node_dict['colors'] = data.colors
            
            result[name] = node_dict
        
        return result


class GraphSpec:
    """Specification for a 2D graph (immutable, analogous to ParameterSpec)."""
    
    def __init__(
        self,
        name: str,
        title: str = "Graph",
        xlabel: str = "X",
        ylabel: str = "Y",
        sample_fn: Optional[Callable[[], Tuple[float, float]]] = None,
        max_samples: int = 1000,
        ylim: Optional[Tuple[float, float]] = None
    ):
        """
        Define a graph specification with lambda-based sampling.
        
        Args:
            name: Unique identifier
            title: Graph title
            xlabel: X-axis label
            ylabel: Y-axis label
            sample_fn: Lambda that returns (x, y) tuple from member vars
            max_samples: Maximum samples to keep
            ylim: Fixed Y-axis limits (optional)
        """
        self.name = name
        self.title = title
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.sample_fn = sample_fn
        self.max_samples = max_samples
        self.ylim = ylim


class GraphState:
    """Runtime state for a 2D graph (stores sampled data)."""
    
    def __init__(self, spec: GraphSpec):
        """
        Create runtime state for a graph from its spec.
        
        Args:
            spec: Graph specification
        """
        self.spec = spec
        self.x_data: List[float] = []
        self.y_data: List[float] = []
        
        self._lock = threading.Lock()
        self._last_sample_time = 0.0
        self._sample_interval = 0.05  # Sample at 20Hz max
        
    def update_from_lambda(self):
        """Call spec's lambda to get new sample and add to data."""
        if self.spec.sample_fn is None:
            return
            
        # Rate limit sampling
        import time
        current_time = time.time()
        if current_time - self._last_sample_time < self._sample_interval:
            return
            
        self._last_sample_time = current_time
        
        with self._lock:
            try:
                x, y = self.spec.sample_fn()
                self.x_data.append(x)
                self.y_data.append(y)
                
                # Keep only max_samples
                if len(self.x_data) > self.spec.max_samples:
                    self.x_data = self.x_data[-self.spec.max_samples:]
                    self.y_data = self.y_data[-self.spec.max_samples:]
            except Exception as e:
                # Silently ignore lambda errors
                pass
            
    def clear(self):
        """Clear all data."""
        with self._lock:
            self.x_data.clear()
            self.y_data.clear()
            
    def get_snapshot(self) -> dict:
        """Get thread-safe snapshot of current state."""
        with self._lock:
            return {
                'name': self.spec.name,
                'title': self.spec.title,
                'xlabel': self.spec.xlabel,
                'ylabel': self.spec.ylabel,
                'x_data': self.x_data.copy(),
                'y_data': self.y_data.copy(),
                'ylim': self.spec.ylim
            }


class VisualizationState:
    """
    Container for visualization state with lambda-based data generation.
    
    Mirrors ParameterState design but in reverse:
    - ParameterState: UI values → sync_fn → member vars (input to retargeter)
    - VisualizationState: member vars → lambdas → UI (output from retargeter)
    
    Follows ParameterState pattern:
    - Specs (Node3DSpec, GraphSpec) declared upfront in constructor
    - Runtime state created from specs
    - Values pulled lazily via lambdas
    
    Data flow:
    - Node positions/text/vectors: Pulled lazily when UI renders (via get_snapshot)
    - Graph samples: Pushed after each compute() (via sync_all, called by BaseRetargeter)
    
    This ensures:
    - Graphs sample at compute frequency (e.g., 60Hz), not render frequency
    - Node data is always current when rendered
    - No manual update calls needed in compute()
    
    Usage in retargeter:
        def __init__(self):
            # Declare visualization specs (like parameter specs)
            node_specs = [
                Node3DSpec(
                    "hand",
                    position_fn=lambda: self.hand_pos,
                    text_fn=lambda: f"Hand\\n{self.hand_pos[0]:.2f}",
                    vector_fn=lambda: self.velocity,
                    color=(0.2, 0.6, 1.0),
                    size=15.0
                )
            ]
            
            graph_specs = [
                GraphSpec(
                    "error",
                    "Tracking Error",
                    "Time (s)",
                    "Error (m)",
                    sample_fn=lambda: (self.time, self.error),
                    ylim=(0.0, 1.0)
                )
            ]
            
            viz_state = VisualizationState("MyRetargeter", node_specs, graph_specs)
            super().__init__(name, visualization_state=viz_state)
            
        def compute(self, inputs, outputs):
            # Just update member vars - visualization syncs automatically!
            self.hand_pos = new_position
            self.velocity = new_velocity
            self.time += dt
            self.error = compute_error()
            # BaseRetargeter calls viz_state.sync_all() after this
            
            return outputs
    """
    
    def __init__(
        self,
        name: str,
        render_space_specs: Optional[List[RenderSpaceSpec]] = None,
        graph_specs: Optional[List[GraphSpec]] = None
    ):
        """
        Create visualization state from specifications.
        
        Args:
            name: Name of the retargeter (for window title)
            render_space_specs: List of render space specifications (each with its own nodes).
                If None, no 3D visualization is shown.
            graph_specs: List of graph specifications
            
        Raises:
            ValueError: If duplicate render space or graph names found
        """
        self.name = name
        
        # Store render space specs as ordered list
        self._render_space_specs: List[RenderSpaceSpec] = render_space_specs if render_space_specs else []
        
        # Validate no duplicate render space names
        seen_names = set()
        for spec in self._render_space_specs:
            if spec.name in seen_names:
                raise ValueError(f"Duplicate render space name: {spec.name}")
            seen_names.add(spec.name)
        
        # Store graph specs and create states
        self._graph_specs: Dict[str, GraphSpec] = {}
        self._graph_states: Dict[str, GraphState] = {}
        if graph_specs:
            for spec in graph_specs:
                if spec.name in self._graph_specs:
                    raise ValueError(f"Duplicate graph name: {spec.name}")
                self._graph_specs[spec.name] = spec
                self._graph_states[spec.name] = GraphState(spec)
    
    def sync_all(self, profile: bool = False):
        """
        Sync node data from lambdas to pre-allocated buffers. Called from compute thread.
        
        This is the FAST path - just copies values to buffers, no object creation.
        The heavy work (world transforms, snapshot creation) is deferred to get_snapshot().
        
        Args:
            profile: If True, print timing information for performance analysis
        """
        if profile:
            import time
            t0 = time.perf_counter()
        
        # Sync render space buffers (fast - just copies values)
        for rs in self._render_space_specs:
            rs.sync(profile=profile)
        
        if profile:
            t1 = time.perf_counter()
        
        # Sample graph data
        for graph_state in self._graph_states.values():
            graph_state.update_from_lambda()
        
        if profile:
            t2 = time.perf_counter()
            print(f"[PROFILE] sync_all: render_spaces={1000*(t1-t0):.3f}ms, graphs={1000*(t2-t1):.3f}ms, total={1000*(t2-t0):.3f}ms")
        
    def get_snapshot(self, profile: bool = False) -> dict:
        """
        Get snapshot with world transforms computed. Called from UI thread.
        
        This builds the full snapshot from the pre-synced buffers.
        The heavy work happens here, on the UI thread, not the compute thread.
        
        Args:
            profile: If True, print timing information for performance analysis
        
        Returns:
            Complete visualization snapshot
        """
        if profile:
            import time
            t0 = time.perf_counter()
        
        # Build render space snapshots (does world transforms on UI thread)
        render_spaces = [rs.get_snapshot(profile=profile) for rs in self._render_space_specs]
        
        if profile:
            t1 = time.perf_counter()
        
        # Get graph snapshots
        graphs = {name: state.get_snapshot() for name, state in self._graph_states.items()}
        
        if profile:
            t2 = time.perf_counter()
            print(f"[PROFILE] VisualizationState.get_snapshot: render_spaces={1000*(t1-t0):.3f}ms, graphs={1000*(t2-t1):.3f}ms, total={1000*(t2-t0):.3f}ms")
        
        return {
            'name': self.name,
            'render_spaces': render_spaces,
            'graphs': graphs,
        }
    
    def set_render_space_enabled(self, name: str, enabled: bool) -> None:
        """
        Enable/disable a render space for syncing. Called from UI thread.
        
        When disabled, sync() skips this render space, saving compute overhead.
        UI should call this when a render space section is collapsed.
        
        Args:
            name: Render space name
            enabled: True to enable syncing, False to skip
        """
        for rs in self._render_space_specs:
            if rs.name == name:
                rs.enabled = enabled
                return
    
    @property
    def render_space_specs(self) -> List[RenderSpaceSpec]:
        """Get list of render space specs (for UI to access enabled flags)."""
        return self._render_space_specs
