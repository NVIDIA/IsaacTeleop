# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Interface module for retargeting engine type system."""

from .base_retargeter import BaseRetargeter
from .output_combiner import OutputCombiner
from .parameter_state import ParameterState
from .retargeter_stats import RetargeterStats
from .retargeter_core_types import (
    ExecutionContext,
    GraphExecutable,
    OutputSelector,
    RetargeterIO,
    RetargeterIOType,
)
from .retargeter_subgraph import RetargeterSubgraph
from .tensor import UNSET_VALUE, Tensor
from .tensor_group import TensorGroup
from .tensor_group_type import TensorGroupType
from .tensor_type import TensorType
from .tunable_parameter import (
    BoolParameter,
    FloatParameter,
    IntParameter,
    ParameterSpec,
    VectorParameter,
)

# Visualization state (optional)
try:
    from .visualization_state import (
        VisualizationState,
        RenderSpaceSpec,
        GraphSpec,
    )
    from .node_specs import (
        # Data types (for rendering)
        Node3D,
        TransformData,
        SphereData,
        MarkerData,
        ArrowData,
        LineData,
        TextData,
        # Batch data types (for efficient rendering of many instances)
        LineListData,
        MarkerListData,
        SphereListData,
        # Spec types (for advanced usage)
        NodeSpec,
        TransformNodeSpec,
        SphereNodeSpec,
        MarkerNodeSpec,
        ArrowNodeSpec,
        LineNodeSpec,
        TextNodeSpec,
        # Batch spec types (for efficient rendering of many instances)
        LineListNodeSpec,
        MarkerListNodeSpec,
        SphereListNodeSpec,
    )
    _HAS_VISUALIZATION_STATE = True
except ImportError:
    # numpy not available
    _HAS_VISUALIZATION_STATE = False

__all__ = [
    "TensorType",
    "TensorGroupType",
    "Tensor",
    "TensorGroup",
    "UNSET_VALUE",
    "BaseRetargeter",
    "RetargeterSubgraph",
    "OutputCombiner",
    "OutputSelector",
    "RetargeterIO",
    "RetargeterIOType",
    "ExecutionContext",
    "GraphExecutable",
    "ParameterSpec",
    "BoolParameter",
    "FloatParameter",
    "IntParameter",
    "VectorParameter",
    "ParameterState",
    "RetargeterStats",
]

if _HAS_VISUALIZATION_STATE:
    __all__.extend([
        # State containers
        "VisualizationState",
        "RenderSpaceSpec",
        "GraphSpec",
        # Data types (for rendering)
        "Node3D",
        "TransformData",
        "SphereData",
        "MarkerData",
        "ArrowData",
        "LineData",
        "TextData",
        # Batch data types (for efficient rendering of many instances)
        "LineListData",
        "MarkerListData",
        "SphereListData",
        # Spec types (for advanced usage)
        "NodeSpec",
        "TransformNodeSpec",
        "SphereNodeSpec",
        "MarkerNodeSpec",
        "ArrowNodeSpec",
        "LineNodeSpec",
        "TextNodeSpec",
        # Batch spec types (for efficient rendering of many instances)
        "LineListNodeSpec",
        "MarkerListNodeSpec",
        "SphereListNodeSpec",
    ])
