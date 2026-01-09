# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
RetargeterSubgraph - Represents a connected subgraph of retargeters.

A subgraph wraps a target retargeter module with its input connections,
enabling composition of retargeters into larger computational graphs.
"""

from abc import ABC
from typing import Dict
from .retargeter_core_types import GraphExecutable, BaseExecutable, RetargeterIOType, ExecutionContext, OutputSelector, RetargeterIO


class RetargeterSubgraph(GraphExecutable):
    """
    A subgraph of retargeters with resolved input connections.
    
    This class wraps a target retargeter module along with its input connections,
    enabling it to be executed as part of a larger computational graph. It handles:
    - Resolving inputs from connected source modules
    - Caching computation results to avoid redundant executions
    - Executing the target module with resolved inputs
    
    The subgraph is created automatically by calling connect() on a BaseRetargeter.
    """

    def __init__(self, target_module: BaseExecutable, input_connections: Dict[str, OutputSelector], output_types: RetargeterIOType) -> None:
        """
        Initialize a retargeter subgraph.
        
        Args:
            target_module: The retargeter module to execute with connected inputs
            input_connections: Dict mapping input names to their source OutputSelectors
            output_types: Type specification for the outputs (from target module)
        """
        self._target_module = target_module
        self._input_connections = input_connections
        self._output_types = output_types
    
    def output_types(self) -> RetargeterIOType:
        """
        Return the output type specification for this subgraph.
        
        The output types match those of the wrapped target module.
        
        Returns:
            Dict[str, TensorGroupType] - Output type specification
        """
        return self._output_types
    
    def _compute_in_graph(self, context: ExecutionContext) -> RetargeterIO:
        """
        Compute the subgraph within a graph execution context.
        
        This method:
        1. Checks for cached results to avoid redundant computation
        2. Resolves inputs by executing connected source modules
        3. Executes the target module with resolved inputs
        4. Caches the results for future use
        
        Args:
            context: The execution context containing leaf inputs and cache
            
        Returns:
            Dict[str, TensorGroup] - The computed output tensor groups
        """
        # Check the execution context for cached results.
        cached_outputs = context.get_cached(id(self))
        if cached_outputs is not None:
            return cached_outputs

        # Resolve inputs from connected modules
        inputs = {}
        for input_name, input_selector in self._input_connections.items():
            source_outputs = input_selector.module._compute_in_graph(context)
            inputs[input_name] = source_outputs[input_selector.output_name]
        
        # Compute target module
        outputs = self._target_module._compute_without_context(inputs)
        context.cache(id(self), outputs)
        return outputs

    def __call__(self, inputs: Dict[str, RetargeterIO]) -> RetargeterIO:
        """
        Execute the subgraph as a callable.
        
        This creates a new execution context with the provided leaf inputs
        and executes the subgraph.
        
        Args:
            inputs: Dict mapping leaf module names to their input tensor groups
            
        Returns:
            Dict[str, TensorGroup] - The computed output tensor groups
        """
        return self._compute_in_graph(ExecutionContext(inputs))
