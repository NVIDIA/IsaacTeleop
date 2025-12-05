# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Sample Retargeter Module.

Example implementation that demonstrates multiple input collections.

Inputs:
- "values": TensorGroup with two floats (x, y)
- "params": TensorGroup with two floats (scale, offset)

Outputs:
- "results": TensorGroup with three floats (scaled_x, scaled_y, sum)

Transformation:
- scaled_x = x * scale + offset
- scaled_y = y * scale + offset
- sum = scaled_x + scaled_y
"""

from typing import Dict
from ..interface.retargeting_module import BaseRetargeter, RetargeterIO
from ..interface.tensor_group_type import TensorGroupType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import FloatType


class SampleRetargeter(BaseRetargeter):
    """
    Sample retargeter demonstrating multiple input collections.
    
    Inputs:
        - "values": x and y floats
        - "params": scale and offset floats
    
    Outputs:
        - "results": scaled_x, scaled_y, and sum floats
    
    Transformation:
        - scaled_x = x * scale + offset
        - scaled_y = y * scale + offset
        - sum = scaled_x + scaled_y
    """
    
    def __init__(self, name: str) -> None:
        """
        Initialize sample retargeter.
        
        Args:
            name: Name identifier for this retargeter (must be unique)
        """
        super().__init__(name=name)
    
    def input_spec(self) -> RetargeterIO:
        """Define input collections."""
        return {
            "values": TensorGroupType("values", [
                FloatType("x"),
                FloatType("y")
            ]),
            "params": TensorGroupType("params", [
                FloatType("scale"),
                FloatType("offset")
            ])
        }
    
    def output_spec(self) -> RetargeterIO:
        """Define output collections."""
        return {
            "results": TensorGroupType("results", [
                FloatType("scaled_x"),
                FloatType("scaled_y"),
                FloatType("sum")
            ])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Execute the retargeting transformation.
        
        Args:
            inputs: Dict with "values" and "params" TensorGroups
            outputs: Dict with "results" TensorGroup (pre-allocated)
        """
        # Get input groups by name
        values_group = inputs["values"]
        params_group = inputs["params"]
        output_group = outputs["results"]
        
        # Get input values by index (O(1) access)
        x = values_group[0]      # "x" at index 0
        y = values_group[1]      # "y" at index 1
        scale = params_group[0]  # "scale" at index 0
        offset = params_group[1] # "offset" at index 1
        
        # Compute transformations and write directly to output
        scaled_x = x * scale + offset
        scaled_y = y * scale + offset
        sum_value = scaled_x + scaled_y
        
        output_group[0] = scaled_x   # "scaled_x" at index 0
        output_group[1] = scaled_y   # "scaled_y" at index 1
        output_group[2] = sum_value  # "sum" at index 2

