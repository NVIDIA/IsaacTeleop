# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Simplified Retargeting Engine.

A modular retargeting system based on composable RetargetingModule objects.
Modules are connected using the connect() method which immediately returns
a new combined module.

Runtime Validation:
    By default, runtime validation is enabled for all tensor operations.
    This provides safety and helpful error messages but has a performance cost.
    
    To disable for production:
        from retargeting_engine import set_runtime_validation
        set_runtime_validation(False)
    
    Or set environment variable:
        export RETARGETING_RUNTIME_VALIDATION=0

Example Retargeters:
    Example retargeting modules are available in the 'examples' submodule:
        from teleopcore.retargeting_engine.examples import SampleRetargeter, GripperRetargeter
    
XRIO Sources:
    XRIO source modules for reading tracker data:
        from teleopcore.retargeting_engine.sources import ControllersSource, HandsSource, HeadSource
"""

from .interface.retargeting_module import RetargetingModule, BaseRetargeter, RetargeterIO, OutputSelector
from .interface.tensor_group_type import TensorGroupType
from .interface.tensor_group import TensorGroup
from .interface.tensor import Tensor, set_runtime_validation, is_runtime_validation_enabled
from .interface.connected_module import ConnectedModule
from .interface.output_layer import OutputLayer
from .tensor_types import FloatType, IntType, BoolType, NDArrayType, DLDataType, DLDeviceType

__all__ = [
    "RetargetingModule",
    "BaseRetargeter",
    "RetargeterIO",
    "OutputSelector",
    "TensorGroupType",
    "TensorGroup",
    "Tensor",
    "ConnectedModule",
    "OutputLayer",
    "FloatType",
    "IntType",
    "BoolType",
    "NDArrayType",
    "DLDataType",
    "DLDeviceType",
    "set_runtime_validation",
    "is_runtime_validation_enabled",
]

