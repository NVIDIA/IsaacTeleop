# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
OutputCombiner - Combines outputs from multiple retargeters into a single output collection.

This is a GraphExecutable that can be used as a source in further connections.
"""

from typing import Dict
from .retargeter_core_types import GraphExecutable, ExecutionContext, OutputSelector, RetargeterIO, RetargeterIOType
from .tensor_group import TensorGroup


class OutputCombiner(GraphExecutable):
    """
    A graph executable that combines outputs from multiple retargeters with custom names.
    
    OutputCombiner is itself a GraphExecutable, so it can be used as a source in further
    connections and benefits from execution caching.
    
    Example:
        # Create retargeters
        left = LeftHandRetargeter("left")
        right = RightHandRetargeter("right")
        
        # Combine their outputs with custom names
        combiner = OutputCombiner({
            "left_pose": left.output("pose"),
            "right_pose": right.output("pose")
        })
        
        # Use it in execution
        outputs = combiner({"left": {...}, "right": {...}})
        left_pose = outputs["left_pose"]
        right_pose = outputs["right_pose"]
        
        # Can also be used as a source for further connections
        next_module = NextModule("next")
        connected = next_module.connect({
            "combined": combiner.output("left_pose")
        })
    """
    
    def __init__(self, output_mapping: Dict[str, OutputSelector]):
        """
        Initialize an output combiner.
        
        Args:
            output_mapping: Dict mapping custom output names to OutputSelectors
                           e.g., {"left_pose": left.output("pose")}
        
        Raises:
            ValueError: If output_mapping is empty
            TypeError: If any value is not an OutputSelector
        """
        if not output_mapping:
            raise ValueError("Must provide at least one output to combine")
        
        for key, selector in output_mapping.items():
            if not isinstance(selector, OutputSelector):
                raise TypeError(
                    f"Output '{key}': Expected OutputSelector, got {type(selector).__name__}"
                )
        
        self.output_mapping = output_mapping
        
        # Build output types from the source modules
        self._output_types: RetargeterIOType = {}
        for custom_name, selector in output_mapping.items():
            source_types = selector.module.output_types()
            if selector.output_name not in source_types:
                raise ValueError(
                    f"Output '{selector.output_name}' not found in source module. "
                    f"Available outputs: {list(source_types.keys())}"
                )
            self._output_types[custom_name] = source_types[selector.output_name]
    
    def output_types(self) -> RetargeterIOType:
        """
        Return the output type specification for this combiner.
        
        Returns:
            Dict[str, TensorGroupType] - Output type specification
        """
        return self._output_types
    
    def _compute_in_graph(self, context: ExecutionContext) -> RetargeterIO:
        """
        Compute the combiner in a graph context.
        
        This executes each source module and gathers their outputs with custom names.
        
        Args:
            context: The execution context for caching
            
        Returns:
            Dict[str, TensorGroup] - Combined outputs with custom names
        """
        # Check if we've already computed this combiner
        outputs = context.get_cached(id(self))
        if outputs is not None:
            return outputs
        
        # Execute each source and gather outputs
        outputs = {}
        for custom_name, selector in self.output_mapping.items():
            # Execute the source module (with caching)
            source_outputs = selector.module._compute_in_graph(context)
            
            # Get the specific output
            outputs[custom_name] = source_outputs[selector.output_name]
        
        # Cache the combined outputs
        context.cache(id(self), outputs)
        return outputs
    
    def __call__(self, inputs: Dict[str, RetargeterIO]) -> RetargeterIO:
        """
        Execute the combiner as a callable (for running outside of a graph context).
        
        Args:
            inputs: Dict[module_name, Dict[str, TensorGroup]] - Inputs for leaf modules
            
        Returns:
            Dict[str, TensorGroup] - Combined outputs with custom names
        """
        return self._compute_in_graph(ExecutionContext(inputs))

