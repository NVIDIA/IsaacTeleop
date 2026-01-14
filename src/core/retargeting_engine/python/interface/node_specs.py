# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
3D node data types and specifications for visualization.

Architecture:
=============

1. Node Data Types (dataclasses)
   - Simple containers for rendering parameters
   - Base class: Node3D (position, orientation, visible)
   - Subclasses: TransformData, SphereData, MarkerData, ArrowData, LineData, TextData

2. NodeSpec Classes (lightweight descriptors)
   - NodeSpec holds: name, hierarchy, update function, template data
   - Does NOT hold the actual buffered data (that's in RenderSpaceSpec)
   - update(data) takes the data to update as a parameter

3. RenderSpaceSpec (owns the global triple buffer)
   - Contains THREE complete copies of all node data
   - Buffer indices: WRITE, READY, READ
   - O(1) swap for ALL nodes (just 2 integer assignments)
   
   Triple Buffer Flow:
   - Compute: updates nodes in WRITE buffer, then swaps WRITE↔READY
   - UI: swaps READY↔READ (if dirty), then reads from READ
   
   Benefits:
   - Lock protects only 2 integer swaps (nanoseconds)
   - Scales to thousands of nodes with no per-node overhead

4. Factory Functions (simplified API)
   - TransformNode(), SphereNode(), MarkerNode(), ArrowNode(), LineNode(), TextNode()
   - Accept static values or lambdas for dynamic parameters

Thread Safety:
==============
- Compute thread: sync() updates WRITE buffer, then ONE global swap
- UI thread: get_snapshot() does ONE global swap, then reads from READ
- Minimal lock contention - each swap is just 2 integer assignments
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union
import threading

import numpy as np


# =============================================================================
# Helper Functions for Transform Computation
# =============================================================================

def _quat_multiply(q1: np.ndarray, q2: np.ndarray, out: np.ndarray) -> None:
    """
    Multiply two quaternions [x, y, z, w], storing result in out array.
    
    Args:
        q1: First quaternion [x, y, z, w]
        q2: Second quaternion [x, y, z, w]
        out: Output array to store result [x, y, z, w]
    """
    x1, y1, z1, w1 = q1[0], q1[1], q1[2], q1[3]
    x2, y2, z2, w2 = q2[0], q2[1], q2[2], q2[3]
    
    out[0] = w1*x2 + x1*w2 + y1*z2 - z1*y2
    out[1] = w1*y2 - x1*z2 + y1*w2 + z1*x2
    out[2] = w1*z2 + x1*y2 - y1*x2 + z1*w2
    out[3] = w1*w2 - x1*x2 - y1*y2 - z1*z2


def _quat_rotate_vector(q: np.ndarray, v: np.ndarray, out: np.ndarray) -> None:
    """
    Rotate a vector by a quaternion, storing result in out array.
    
    Args:
        q: Quaternion [x, y, z, w]
        v: Vector [x, y, z]
        out: Output array to store result [x, y, z]
    """
    qx, qy, qz, qw = q[0], q[1], q[2], q[3]
    vx, vy, vz = v[0], v[1], v[2]
    
    # Using formula: v' = v + 2 * cross(q.xyz, cross(q.xyz, v) + qw * v)
    # Inline cross products to avoid allocations
    
    # cross1 = cross(q.xyz, v) + qw * v
    c1x = qy*vz - qz*vy + qw*vx
    c1y = qz*vx - qx*vz + qw*vy
    c1z = qx*vy - qy*vx + qw*vz
    
    # cross2 = cross(q.xyz, cross1)
    c2x = qy*c1z - qz*c1y
    c2y = qz*c1x - qx*c1z
    c2z = qx*c1y - qy*c1x
    
    out[0] = vx + 2.0*c2x
    out[1] = vy + 2.0*c2y
    out[2] = vz + 2.0*c2z


# =============================================================================
# Node Data Types (rendering parameters only)
# =============================================================================

@dataclass
class Node3D:
    """Base node data with transform and visibility."""
    position: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))
    orientation: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 0.0, 1.0]))
    visible: bool = True


@dataclass
class TransformData(Node3D):
    """Transform-only node data (no visual geometry)."""
    pass


@dataclass
class SphereData(Node3D):
    """Sphere node data. Size is always in world-space units (meters)."""
    size: float = 0.01  # World-space radius in meters
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass
class MarkerData(Node3D):
    """Marker node data. Size is always in screen-space pixels."""
    size: float = 10.0  # Screen-space radius in pixels
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass
class ArrowData(Node3D):
    """Arrow node data."""
    length: float = 1.0
    width: float = 2.0
    color: Tuple[float, float, float] = (1.0, 0.0, 0.0)


@dataclass
class LineData(Node3D):
    """Line node data."""
    end_point: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 1.0]))
    width: float = 1.0
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass
class TextData(Node3D):
    """Text node data."""
    text: str = ""
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)


# =============================================================================
# Batch Node Data Types (arrays for efficient rendering of many instances)
# =============================================================================

@dataclass
class LineListData(Node3D):
    """
    Batch line data - holds N lines as numpy arrays.
    
    Inherits position/orientation from Node3D for world transform of entire batch.
    All item arrays have shape (N, ...) where N is the number of lines.
    Item positions are relative to the batch's world transform.
    """
    count: int = 0  # Number of active lines
    # Per-item data (positions relative to batch origin)
    item_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))  # (N, 3) start positions
    item_orientations: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))  # (N, 4) quaternions [x,y,z,w]
    end_points: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))  # (N, 3) local end points
    widths: np.ndarray = field(default_factory=lambda: np.ones(0))  # (N,) line widths
    colors: np.ndarray = field(default_factory=lambda: np.ones((0, 3)))  # (N, 3) RGB colors


@dataclass
class MarkerListData(Node3D):
    """
    Batch marker data - holds N markers as numpy arrays.
    
    Inherits position/orientation from Node3D for world transform of entire batch.
    All item arrays have shape (N, ...) where N is the number of markers.
    Item positions are relative to the batch's world transform.
    """
    count: int = 0  # Number of active markers
    # Per-item data (positions relative to batch origin)
    item_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))  # (N, 3) positions
    item_orientations: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))  # (N, 4) quaternions
    sizes: np.ndarray = field(default_factory=lambda: np.ones(0) * 10.0)  # (N,) pixel sizes
    colors: np.ndarray = field(default_factory=lambda: np.ones((0, 3)))  # (N, 3) RGB colors


@dataclass
class SphereListData(Node3D):
    """
    Batch sphere data - holds N spheres as numpy arrays.
    
    Inherits position/orientation from Node3D for world transform of entire batch.
    All item arrays have shape (N, ...) where N is the number of spheres.
    Item positions are relative to the batch's world transform.
    Sizes are in world-space units (meters), not screen pixels.
    """
    count: int = 0  # Number of active spheres
    # Per-item data (positions relative to batch origin)
    item_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))  # (N, 3) positions
    item_orientations: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))  # (N, 4) quaternions
    sizes: np.ndarray = field(default_factory=lambda: np.ones(0) * 0.01)  # (N,) world-space sizes in meters
    colors: np.ndarray = field(default_factory=lambda: np.ones((0, 3)))  # (N, 3) RGB colors


# =============================================================================
# Node Specifications (double-buffered data with update lambdas)
# =============================================================================

class NodeSpec:
    """
    Base node specification.
    
    NodeSpec is a lightweight descriptor that holds:
    - Name and hierarchy (parent/children)
    - Update function to refresh data
    - Template data for initialization
    
    The actual triple-buffered data lives in RenderSpaceSpec, not here.
    This allows O(1) buffer swaps at the RenderSpaceSpec level instead of O(n).
    """
    
    def __init__(
        self,
        name: str,
        initial_data: Node3D,
        update_fn: Optional[Callable[[Node3D], None]] = None,
        children: Optional[List['NodeSpec']] = None,
    ):
        """
        Create a node specification.
        
        Args:
            name: Unique identifier
            initial_data: Initial/template node data values
            update_fn: Lambda that updates node data (None = static node)
            children: Optional list of child node specs
        """
        self.name = name
        self.children = children if children is not None else []
        self.parent: Optional[str] = None  # Set during hierarchy flattening
        
        # Store update function - None means static node (skip updates)
        self._update_fn = update_fn
        
        # Template data for buffer initialization (not the live data)
        self._template_data = initial_data
    
    def create_data_instance(self) -> Node3D:
        """Create a new instance of node data from template. Override in subclasses."""
        template = self._template_data
        return Node3D(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible
        )
    
    def update(self, data: Node3D) -> None:
        """
        Update node data using update lambda. Called from compute thread.
        
        Args:
            data: The node data instance to update (from global write buffer)
        """
        if self._update_fn is not None:
            self._update_fn(data)
    
    def get_node_type(self) -> str:
        """Get node type string for rendering."""
        return "transform"


class TransformNodeSpec(NodeSpec):
    """
    Transform-only node specification - no visual geometry.
    
    Useful for creating invisible parent nodes in hierarchies.
    """
    
    def __init__(
        self,
        name: str,
        initial_data: TransformData,
        update_fn: Callable[[TransformData], None],
        children: Optional[List[NodeSpec]] = None,
    ):
        super().__init__(name, initial_data, update_fn, children)
    
    def create_data_instance(self) -> TransformData:
        template = self._template_data
        return TransformData(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible
        )
    
    def get_node_type(self) -> str:
        return "transform"


class SphereNodeSpec(NodeSpec):
    """
    Sphere node specification (world-space size).
    
    Internally uses SphereListData with count=1 for unified rendering.
    The user-facing API still uses SphereData for convenience.
    """
    
    def __init__(
        self,
        name: str,
        initial_data: SphereData,
        update_fn: Optional[Callable[[SphereData], None]] = None,
        children: Optional[List[NodeSpec]] = None,
    ):
        # Store user's update_fn and create a SphereData for their interface
        self._user_update_fn = update_fn
        self._user_sphere_data = SphereData(
            position=initial_data.position.copy(),
            orientation=initial_data.orientation.copy(),
            visible=initial_data.visible,
            size=initial_data.size,
            color=initial_data.color,
        )
        
        # Create internal SphereListData with count=1
        list_data = SphereListData(
            position=initial_data.position.copy(),
            orientation=initial_data.orientation.copy(),
            visible=initial_data.visible,
            count=1,
            item_positions=np.zeros((1, 3)),  # Relative to batch position (identity)
            item_orientations=np.array([[0.0, 0.0, 0.0, 1.0]]),
            sizes=np.array([initial_data.size]),
            colors=np.array([[initial_data.color[0], initial_data.color[1], initial_data.color[2]]]),
        )
        
        # Pass our wrapper as the update_fn if user provided one
        wrapper_fn = self._wrapper_update_fn if update_fn is not None else None
        super().__init__(name, list_data, wrapper_fn, children)
    
    def _wrapper_update_fn(self, data: SphereListData) -> None:
        """Wrapper that translates SphereData updates to SphereListData."""
        # Call user's update with SphereData interface
        self._user_update_fn(self._user_sphere_data)
        
        # Copy from SphereData to SphereListData
        data.position[:] = self._user_sphere_data.position
        data.orientation[:] = self._user_sphere_data.orientation
        data.visible = self._user_sphere_data.visible
        data.sizes[0] = self._user_sphere_data.size
        data.colors[0, 0] = self._user_sphere_data.color[0]
        data.colors[0, 1] = self._user_sphere_data.color[1]
        data.colors[0, 2] = self._user_sphere_data.color[2]
    
    def create_data_instance(self) -> SphereListData:
        template = self._template_data
        return SphereListData(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible,
            count=template.count,
            item_positions=template.item_positions.copy(),
            item_orientations=template.item_orientations.copy(),
            sizes=template.sizes.copy(),
            colors=template.colors.copy(),
        )
    
    def get_node_type(self) -> str:
        return "sphere_list"


class MarkerNodeSpec(NodeSpec):
    """
    Marker node specification (screen-space size in pixels).
    """
    
    def __init__(
        self,
        name: str,
        initial_data: MarkerData,
        update_fn: Callable[[MarkerData], None],
        children: Optional[List[NodeSpec]] = None,
    ):
        super().__init__(name, initial_data, update_fn, children)

    @property
    def node_type(self) -> str:
        return 'marker'
    
    def create_data_instance(self) -> MarkerData:
        template = self._template_data
        return MarkerData(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible,
            size=template.size,
            color=template.color,
        )
    
    def get_node_type(self) -> str:
        return "marker"


class ArrowNodeSpec(NodeSpec):
    """
    Arrow node specification.
    
    Arrow points along +Z axis of its orientation.
    """
    
    def __init__(
        self,
        name: str,
        initial_data: ArrowData,
        update_fn: Callable[[ArrowData], None],
        children: Optional[List[NodeSpec]] = None,
    ):
        super().__init__(name, initial_data, update_fn, children)
    
    def create_data_instance(self) -> ArrowData:
        template = self._template_data
        return ArrowData(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible,
            length=template.length,
            width=template.width,
            color=template.color
        )
    
    def get_node_type(self) -> str:
        return "arrow"


class LineNodeSpec(NodeSpec):
    """
    Line node specification.
    
    Line goes from local origin to end_point.
    """
    
    def __init__(
        self,
        name: str,
        initial_data: LineData,
        update_fn: Callable[[LineData], None],
        children: Optional[List[NodeSpec]] = None,
    ):
        super().__init__(name, initial_data, update_fn, children)
    
    def create_data_instance(self) -> LineData:
        template = self._template_data
        return LineData(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible,
            end_point=template.end_point.copy(),
            width=template.width,
            color=template.color
        )
    
    def get_node_type(self) -> str:
        return "line"


class TextNodeSpec(NodeSpec):
    """
    Text label node specification.
    
    Renders text at node position.
    """
    
    def __init__(
        self,
        name: str,
        initial_data: TextData,
        update_fn: Callable[[TextData], None],
        children: Optional[List[NodeSpec]] = None,
    ):
        super().__init__(name, initial_data, update_fn, children)
    
    def create_data_instance(self) -> TextData:
        template = self._template_data
        return TextData(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible,
            text=template.text,
            color=template.color
        )
    
    def get_node_type(self) -> str:
        return "text"


# =============================================================================
# Batch Node Specifications (efficient rendering of many instances)
# =============================================================================

class LineListNodeSpec(NodeSpec):
    """
    Batch line list specification - renders N lines from numpy arrays.
    
    Much more efficient than N individual LineNodeSpec when you have
    hundreds or thousands of lines. Single update function updates all lines.
    
    Note: LineListNodeSpec does NOT support hierarchy (no parent transforms).
    All positions are in world space.
    """
    
    def __init__(
        self,
        name: str,
        initial_data: LineListData,
        update_fn: Optional[Callable[[LineListData], None]] = None,
    ):
        # Batch nodes don't support children (they ARE the batch)
        super().__init__(name, initial_data, update_fn, children=None)
    
    def create_data_instance(self) -> LineListData:
        template = self._template_data
        return LineListData(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible,
            count=template.count,
            item_positions=template.item_positions.copy(),
            item_orientations=template.item_orientations.copy(),
            end_points=template.end_points.copy(),
            widths=template.widths.copy(),
            colors=template.colors.copy(),
        )
    
    def get_node_type(self) -> str:
        return "line_list"


class MarkerListNodeSpec(NodeSpec):
    """
    Batch marker list specification - renders N markers from numpy arrays.
    
    Much more efficient than N individual MarkerNodeSpec when you have
    hundreds or thousands of markers. Single update function updates all markers.
    
    Note: MarkerListNodeSpec does NOT support hierarchy (no parent transforms).
    All positions are in world space.
    """
    
    def __init__(
        self,
        name: str,
        initial_data: MarkerListData,
        update_fn: Optional[Callable[[MarkerListData], None]] = None,
    ):
        # Batch nodes don't support children (they ARE the batch)
        super().__init__(name, initial_data, update_fn, children=None)
    
    def create_data_instance(self) -> MarkerListData:
        template = self._template_data
        return MarkerListData(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible,
            count=template.count,
            item_positions=template.item_positions.copy(),
            item_orientations=template.item_orientations.copy(),
            sizes=template.sizes.copy(),
            colors=template.colors.copy(),
        )
    
    def get_node_type(self) -> str:
        return "marker_list"


class SphereListNodeSpec(NodeSpec):
    """
    Batch sphere list specification - renders N spheres from numpy arrays.
    
    Much more efficient than N individual SphereNodeSpec when you have
    hundreds or thousands of spheres. Single update function updates all spheres.
    
    Unlike MarkerListNodeSpec (screen-space pixels), SphereListNodeSpec uses
    world-space sizes in meters, matching the behavior of individual SphereNodeSpec.
    
    Note: SphereListNodeSpec does NOT support hierarchy (no parent transforms).
    All positions are in world space.
    """
    
    def __init__(
        self,
        name: str,
        initial_data: SphereListData,
        update_fn: Optional[Callable[[SphereListData], None]] = None,
    ):
        # Batch nodes don't support children (they ARE the batch)
        super().__init__(name, initial_data, update_fn, children=None)
    
    def create_data_instance(self) -> SphereListData:
        template = self._template_data
        return SphereListData(
            position=template.position.copy(),
            orientation=template.orientation.copy(),
            visible=template.visible,
            count=template.count,
            item_positions=template.item_positions.copy(),
            item_orientations=template.item_orientations.copy(),
            sizes=template.sizes.copy(),
            colors=template.colors.copy(),
        )
    
    def get_node_type(self) -> str:
        return "sphere_list"


# =============================================================================
# Utility Functions
# =============================================================================

def flatten_node_hierarchy(
    node_specs: List[NodeSpec],
    parent_name: Optional[str] = None
) -> Dict[str, NodeSpec]:
    """
    Flatten a hierarchical list of node specs into a flat dict.
    
    Sets parent references on each spec.
    
    Args:
        node_specs: List of root node specs (may have children)
        parent_name: Parent name to set (for recursion)
        
    Returns:
        Flat dict of node name -> spec
    """
    result: Dict[str, NodeSpec] = {}
    
    for spec in node_specs:
        spec.parent = parent_name
        result[spec.name] = spec
        if spec.children:
            result.update(flatten_node_hierarchy(spec.children, spec.name))
    
    return result


@dataclass
class RenderNodeData:
    """Node data with metadata for rendering (includes name, type, parent).
    
    World transforms are stored separately to avoid mutating local data.
    """
    name: str
    node_type: str
    parent: Optional[str]
    data: Node3D
    # World transforms (computed, stored here to avoid allocations)
    world_position: np.ndarray = None  # type: ignore[assignment]
    world_orientation: np.ndarray = None  # type: ignore[assignment]
    
    def __post_init__(self):
        # Pre-allocate world transform arrays
        if self.world_position is None:
            self.world_position = np.zeros(3, dtype=np.float64)
        if self.world_orientation is None:
            self.world_orientation = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)


def compute_world_transforms(
    nodes: Dict[str, RenderNodeData],
    profile: bool = False
) -> None:
    """
    Compute world transforms for all nodes, handling parent-child hierarchy.
    
    Writes to RenderNodeData.world_position and world_orientation fields.
    DOES NOT modify node.data (local transforms are preserved).
    
    Args:
        nodes: Dict of node name -> RenderNodeData (with local transforms)
        profile: If True, print detailed timing breakdown
    """
    if profile:
        import time
        t0 = time.perf_counter()
    
    # Separate roots from children for efficient processing
    roots: List[str] = []
    children: List[str] = []
    for name, node in nodes.items():
        if node.parent is None:
            roots.append(name)
        else:
            children.append(name)
    
    if profile:
        t1 = time.perf_counter()
    
    # Process roots first - copy local to world (in pre-allocated arrays)
    for name in roots:
        node = nodes[name]
        # Copy local to world (no allocation - writes to pre-allocated arrays)
        node.world_position[:] = node.data.position
        node.world_orientation[:] = node.data.orientation
    
    if profile:
        t2 = time.perf_counter()
    
    # Track which nodes have been processed
    processed: set = set(roots)
    
    # Process children (may need multiple passes for deep hierarchies)
    n_children = len(children)
    if n_children > 0:
        pending = children[:]
        max_iterations = 10  # Prevent infinite loops
        
        for _ in range(max_iterations):
            if not pending:
                break
            still_pending = []
            for name in pending:
                node = nodes[name]
                parent_name = node.parent
                
                # Check if parent is already processed
                if parent_name in processed:
                    parent_node = nodes[parent_name]
                    # Compute world transform directly into node's pre-allocated arrays
                    _quat_rotate_vector(parent_node.world_orientation, node.data.position, node.world_position)
                    node.world_position += parent_node.world_position
                    _quat_multiply(parent_node.world_orientation, node.data.orientation, node.world_orientation)
                    processed.add(name)
                else:
                    still_pending.append(name)
            pending = still_pending
    
    if profile:
        t3 = time.perf_counter()
        print(f"[PROFILE] compute_world_transforms: classify={1000*(t1-t0):.3f}ms, roots={1000*(t2-t1):.3f}ms, children={1000*(t3-t2):.3f}ms, n_roots={len(roots)}, n_children={n_children}")


# =============================================================================
# Factory Functions (simplified API)
# =============================================================================

def _resolve_value(value_or_fn, default=None):
    """Get value from static value or callable. Returns default if value is None."""
    if value_or_fn is None:
        return default
    if callable(value_or_fn):
        return value_or_fn()
    return value_or_fn


def _resolve_array(value_or_fn, default):
    """Get array from static value or callable."""
    if value_or_fn is None:
        return default.copy() if isinstance(default, np.ndarray) else np.array(default)
    if callable(value_or_fn):
        val = value_or_fn()
        return val.copy() if isinstance(val, np.ndarray) else np.array(val)
    return value_or_fn.copy() if isinstance(value_or_fn, np.ndarray) else np.array(value_or_fn)


def TransformNode(
    name: str,
    position: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    orientation: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    children: Optional[List[NodeSpec]] = None,
) -> TransformNodeSpec:
    """
    Create a transform-only node (invisible parent for hierarchy).
    
    Args:
        name: Unique identifier
        position: Static array or lambda returning [x, y, z]
        orientation: Static array or lambda returning quaternion [x, y, z, w]
        children: Optional list of child node specs
    
    Returns:
        TransformNodeSpec instance
    """
    initial_data = TransformData(
        position=_resolve_array(position, [0.0, 0.0, 0.0]),
        orientation=_resolve_array(orientation, [0.0, 0.0, 0.0, 1.0]),
        visible=False  # Transform nodes are always invisible
    )
    
    def update_fn(data: TransformData):
        if callable(position):
            data.position[:] = position()
        if callable(orientation):
            data.orientation[:] = orientation()
    
    return TransformNodeSpec(name, initial_data, update_fn, children)


def SphereNode(
    name: str,
    position: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    orientation: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    visible: Union[bool, Callable[[], bool]] = True,
    size: Union[float, Callable[[], float]] = 0.01,
    color: Union[Tuple[float, float, float], Callable[[], Tuple[float, float, float]]] = (1.0, 1.0, 1.0),
    children: Optional[List[NodeSpec]] = None,
) -> SphereNodeSpec:
    """
    Create a sphere node with world-space size.
    
    Size is in world units (meters). Visual size changes with distance.
    
    Args:
        name: Unique identifier
        position: Static array or lambda returning [x, y, z]
        orientation: Static array or lambda returning quaternion [x, y, z, w]
        visible: Static bool or lambda returning bool
        size: Static float or lambda returning float (radius in world units)
        color: Static tuple or lambda returning (r, g, b)
        children: Optional list of child node specs
    
    Returns:
        SphereNodeSpec instance
    """
    initial_data = SphereData(
        position=_resolve_array(position, [0.0, 0.0, 0.0]),
        orientation=_resolve_array(orientation, [0.0, 0.0, 0.0, 1.0]),
        visible=_resolve_value(visible, True),
        size=_resolve_value(size, 0.01),
        color=_resolve_value(color, (1.0, 1.0, 1.0)),
        size_in_pixels=False
    )
    
    def update_fn(data: SphereData):
        if callable(position):
            data.position[:] = position()
        if callable(orientation):
            data.orientation[:] = orientation()
        if callable(visible):
            data.visible = visible()
        if callable(size):
            data.size = size()
        if callable(color):
            data.color = color()
    
    return SphereNodeSpec(name, initial_data, update_fn, children)


def MarkerNode(
    name: str,
    position: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    orientation: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    visible: Union[bool, Callable[[], bool]] = True,
    size: Union[float, Callable[[], float]] = 10.0,
    color: Union[Tuple[float, float, float], Callable[[], Tuple[float, float, float]]] = (1.0, 1.0, 1.0),
    children: Optional[List[NodeSpec]] = None,
) -> MarkerNodeSpec:
    """
    Create a marker node with screen-space size.
    
    Size is in screen pixels. Stays the same size on screen regardless of distance.
    
    Args:
        name: Unique identifier
        position: Static array or lambda returning [x, y, z]
        orientation: Static array or lambda returning quaternion [x, y, z, w]
        visible: Static bool or lambda returning bool
        size: Static float or lambda returning float (size in screen pixels)
        color: Static tuple or lambda returning (r, g, b)
        children: Optional list of child node specs
    
    Returns:
        MarkerNodeSpec instance
    """
    initial_data = SphereData(
        position=_resolve_array(position, [0.0, 0.0, 0.0]),
        orientation=_resolve_array(orientation, [0.0, 0.0, 0.0, 1.0]),
        visible=_resolve_value(visible, True),
        size=_resolve_value(size, 10.0),
        color=_resolve_value(color, (1.0, 1.0, 1.0)),
        size_in_pixels=True
    )
    
    def update_fn(data: SphereData):
        if callable(position):
            data.position[:] = position()
        if callable(orientation):
            data.orientation[:] = orientation()
        if callable(visible):
            data.visible = visible()
        if callable(size):
            data.size = size()
        if callable(color):
            data.color = color()
    
    return MarkerNodeSpec(name, initial_data, update_fn, children)


def ArrowNode(
    name: str,
    position: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    orientation: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    visible: Union[bool, Callable[[], bool]] = True,
    length: Union[float, Callable[[], float]] = 1.0,
    width: Union[float, Callable[[], float]] = 2.0,
    color: Union[Tuple[float, float, float], Callable[[], Tuple[float, float, float]]] = (1.0, 0.0, 0.0),
    children: Optional[List[NodeSpec]] = None,
) -> ArrowNodeSpec:
    """
    Create an arrow node.
    
    Args:
        name: Unique identifier
        position: Static array or lambda returning [x, y, z]
        orientation: Static array or lambda returning quaternion [x, y, z, w]
        visible: Static bool or lambda returning bool
        length: Static float or lambda returning float
        width: Static float or lambda returning float
        color: Static tuple or lambda returning (r, g, b)
        children: Optional list of child node specs
    
    Returns:
        ArrowNodeSpec instance
    """
    initial_data = ArrowData(
        position=_resolve_array(position, [0.0, 0.0, 0.0]),
        orientation=_resolve_array(orientation, [0.0, 0.0, 0.0, 1.0]),
        visible=_resolve_value(visible, True),
        length=_resolve_value(length, 1.0),
        width=_resolve_value(width, 2.0),
        color=_resolve_value(color, (1.0, 0.0, 0.0))
    )
    
    def update_fn(data: ArrowData):
        if callable(position):
            data.position[:] = position()
        if callable(orientation):
            data.orientation[:] = orientation()
        if callable(visible):
            data.visible = visible()
        if callable(length):
            data.length = length()
        if callable(width):
            data.width = width()
        if callable(color):
            data.color = color()
    
    return ArrowNodeSpec(name, initial_data, update_fn, children)


def LineNode(
    name: str,
    position: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    orientation: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    visible: Union[bool, Callable[[], bool]] = True,
    end_point: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    width: Union[float, Callable[[], float]] = 1.0,
    color: Union[Tuple[float, float, float], Callable[[], Tuple[float, float, float]]] = (1.0, 1.0, 1.0),
    children: Optional[List[NodeSpec]] = None,
) -> LineNodeSpec:
    """
    Create a line node.
    
    Args:
        name: Unique identifier
        position: Static array or lambda returning [x, y, z]
        orientation: Static array or lambda returning quaternion [x, y, z, w]
        visible: Static bool or lambda returning bool
        end_point: Static array or lambda returning [x, y, z] (in local space)
        width: Static float or lambda returning float
        color: Static tuple or lambda returning (r, g, b)
        children: Optional list of child node specs
    
    Returns:
        LineNodeSpec instance
    """
    initial_data = LineData(
        position=_resolve_array(position, [0.0, 0.0, 0.0]),
        orientation=_resolve_array(orientation, [0.0, 0.0, 0.0, 1.0]),
        visible=_resolve_value(visible, True),
        end_point=_resolve_array(end_point, [0.0, 0.0, 1.0]),
        width=_resolve_value(width, 1.0),
        color=_resolve_value(color, (1.0, 1.0, 1.0))
    )
    
    def update_fn(data: LineData):
        if callable(position):
            data.position[:] = position()
        if callable(orientation):
            data.orientation[:] = orientation()
        if callable(visible):
            data.visible = visible()
        if callable(end_point):
            data.end_point[:] = end_point()
        if callable(width):
            data.width = width()
        if callable(color):
            data.color = color()
    
    return LineNodeSpec(name, initial_data, update_fn, children)


def TextNode(
    name: str,
    position: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    orientation: Union[np.ndarray, Callable[[], np.ndarray]] = None,
    visible: Union[bool, Callable[[], bool]] = True,
    text: Union[str, Callable[[], str]] = "",
    color: Union[Tuple[float, float, float], Callable[[], Tuple[float, float, float]]] = (1.0, 1.0, 1.0),
    children: Optional[List[NodeSpec]] = None,
) -> TextNodeSpec:
    """
    Create a text node.
    
    Args:
        name: Unique identifier
        position: Static array or lambda returning [x, y, z]
        orientation: Static array or lambda returning quaternion [x, y, z, w]
        visible: Static bool or lambda returning bool
        text: Static string or lambda returning string
        color: Static tuple or lambda returning (r, g, b)
        children: Optional list of child node specs
    
    Returns:
        TextNodeSpec instance
    """
    initial_data = TextData(
        position=_resolve_array(position, [0.0, 0.0, 0.0]),
        orientation=_resolve_array(orientation, [0.0, 0.0, 0.0, 1.0]),
        visible=_resolve_value(visible, True),
        text=_resolve_value(text, ""),
        color=_resolve_value(color, (1.0, 1.0, 1.0))
    )
    
    def update_fn(data: TextData):
        if callable(position):
            data.position[:] = position()
        if callable(orientation):
            data.orientation[:] = orientation()
        if callable(visible):
            data.visible = visible()
        if callable(text):
            data.text = text()
        if callable(color):
            data.color = color()
    
    return TextNodeSpec(name, initial_data, update_fn, children)

