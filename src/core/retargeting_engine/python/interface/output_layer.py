# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
OutputLayer - Gathering outputs from multiple retargeters with custom names.

Implemented as a factory that creates a synthetic passthrough module and
connects it using the standard ConnectedModule infrastructure.
"""

from typing import Dict
from .retargeting_module import BaseRetargeter, OutputSelector, RetargeterIO
from .tensor_group import TensorGroup
from .tensor_group_type import TensorGroupType


def OutputLayer(output_mapping: Dict[str, OutputSelector], name: str):
    """
    Create an output layer that gathers outputs from multiple retargeters with custom names.
    
    This is implemented as a factory function that creates a synthetic passthrough module
    and connects it using the standard ConnectedModule infrastructure. This ensures
    OutputLayer behaves exactly like any other ConnectedModule with proper caching.
    
    Args:
        output_mapping: Dict mapping custom output names to OutputSelectors
                       e.g., {"left_pose": retargeter.output("pose")}
        name: Name for the output layer (must be unique)
    
    Returns:
        A ConnectedModule that gathers the specified outputs with custom names
    
    Raises:
        ValueError: If output_mapping is empty
        TypeError: If any value is not an OutputSelector
    
    Example:
        # Create retargeters
        left_retargeter = LeftHandRetargeter(name="left")
        right_retargeter = RightHandRetargeter(name="right")
        
        # Group their outputs with custom names
        hands = OutputLayer({
            "left_pose": left_retargeter.output("pose"),
            "right_pose": right_retargeter.output("pose")
        }, name="hands")
        
        # Use it like any other retargeting module
        result = hands(inputs)
        left_pose = result["left_pose"]   # Direct access with custom name
        right_pose = result["right_pose"]
        
        # Can also select outputs from OutputLayer
        next_module = NextModule(name="next")
        connected = next_module.connect({
            "left": hands.output("left_pose"),
            "right": hands.output("right_pose")
        })
    """
    if not output_mapping:
        raise ValueError("Must provide at least one output to gather")

    for key, selector in output_mapping.items():
        if not isinstance(selector, OutputSelector):
            raise TypeError(
                f"Output '{key}': Expected OutputSelector, got {type(selector).__name__}"
            )

    # Build output types dict using custom names from the source modules
    output_types: Dict[str, TensorGroupType] = {}
    for custom_name, selector in output_mapping.items():
        source_type = selector.module.get_output_type(selector.output_name)
        output_types[custom_name] = source_type
    
    # Create a synthetic passthrough module inline as a closure
    class _Passthrough(BaseRetargeter):
        """Synthetic module that passes inputs through to outputs unchanged."""
        
        def __init__(self):
            super().__init__(name)
        
        def input_spec(self) -> RetargeterIO:
            """Inputs match outputs - one input per output."""
            return output_types.copy()
        
        def output_spec(self) -> RetargeterIO:
            """Outputs match the custom names from OutputLayer."""
            return output_types.copy()
        
        def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
            """Simply copy inputs to outputs - passthrough."""
            for name in output_types.keys():
                outputs[name] = inputs[name]
    
    # Create and connect the passthrough module
    # This automatically handles caching and execution properly!
    passthrough = _Passthrough()
    return passthrough.connect(output_mapping)
