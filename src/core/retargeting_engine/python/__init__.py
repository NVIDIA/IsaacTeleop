"""
Retargeting Engine v2

A simplified and streamlined system for retargeting motion data with type-safe tensor operations.

Architecture:
- Interface: TensorType, TensorCollection, Tensor, TensorGroup, RetargeterNode, InputNode
- Types: ScalarType (Bool, Int, Float), NumpyArrayType, PyTorchTensorType
- Executor: RetargeterExecutor (simple sequential execution)
- Retargeters: GripperRetargeter and other concrete implementations
"""

# Export interface types
from .interface.tensor_type import TensorType
from .interface.tensor_collection import TensorCollection
from .interface.tensor import Tensor
from .interface.tensor_group import TensorGroup
from .interface.retargeter_node import RetargeterNode
from .interface.input_node import InputNode
from .interface.output_selector import OutputSelector

# Export concrete types
from .tensor_types.examples.scalar_types import ScalarType, BoolType, IntType, FloatType
from .tensor_types.examples.numpy_types import NumpyArrayType
from .tensor_types.examples.pytorch_types import PyTorchTensorType

# Export executor
from .executor.retargeter_executor import RetargeterExecutor

# Export retargeters
from .retargeters import GripperRetargeter

__all__ = [
    # Interface
    "TensorType",
    "TensorCollection",
    "Tensor",
    "TensorGroup",
    "RetargeterNode",
    "InputNode",
    "OutputSelector",
    # Types
    "ScalarType",
    "BoolType",
    "IntType",
    "FloatType",
    "NumpyArrayType",
    "PyTorchTensorType",
    # Executor
    "RetargeterExecutor",
    # Retargeters
    "GripperRetargeter",
]

