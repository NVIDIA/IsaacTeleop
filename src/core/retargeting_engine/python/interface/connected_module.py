# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
ConnectedModule - A compound retargeting module created by connecting sources to a target.

This is created automatically when you call connect() on a BaseRetargeter.
"""

from typing import Dict
from .tensor_group import TensorGroup
from .retargeting_module import BaseRetargeter, OutputSelector, RetargeterIO, RetargetingModule


class ExecutionContext:
    """
    Context for tracking retargeter execution to avoid redundant computation.
    
    When the same retargeter appears multiple times in a pipeline (e.g., one source
    feeding multiple downstream modules), we cache its outputs to avoid recomputing.
    """

    def __init__(self) -> None:
        """Initialize an empty execution context."""
        # Maps retargeter_id to cached output Dict[str, TensorGroup]
        self._cache: Dict[int, Dict[str, TensorGroup]] = {}
        # Public attribute for _call_with_context
        self.outputs: Dict[int, Dict[str, TensorGroup]] = self._cache

    def has_cached(self, retargeter: 'BaseRetargeter') -> bool:
        """Check if a retargeter's outputs are cached."""
        return id(retargeter) in self._cache

    def get_cached(self, retargeter: 'BaseRetargeter') -> Dict[str, TensorGroup]:
        """Get cached outputs for a retargeter."""
        return self._cache[id(retargeter)]

    def cache(self, retargeter: 'BaseRetargeter', outputs: Dict[str, TensorGroup]) -> None:
        """Cache all outputs for a retargeter."""
        self._cache[id(retargeter)] = outputs


class ConnectedModule(RetargetingModule):
    """
    A compound retargeting module created by connecting sources to a target.
    
    The target must be a BaseRetargeter (not compound).
    The sources can be any mix of BaseRetargeter or ConnectedModule instances.
    
    ConnectedModule has:
    - Keyed inputs: Dict[retargeter_name, TensorGroup] organized by leaf retargeters
    - Unkeyed outputs: Dict[output_name, TensorGroup] - flat outputs from target
    
    Can be used with OutputLayer to gather outputs from multiple modules.
    """

    def __init__(
        self,
        name: str,
        target_module: BaseRetargeter,
        connections: Dict[str, OutputSelector]
    ) -> None:
        """
        Initialize a connected module.
        
        Args:
            name: Name for this compound retargeter
            target_module: The base retargeter whose inputs are being connected
            connections: Dict mapping target input names to OutputSelectors
        """
        self._name = name
        self._target_module = target_module
        self._connections = connections
        
        # Collect all unique leaf retargeters from the connections
        self._leaf_retargeters: Dict[str, BaseRetargeter] = {}
        for selector in connections.values():
            self._collect_leaf_retargeters(selector.module)
    
    @property
    def name(self) -> str:
        """Get the name of this connected module."""
        return self._name
    
    def get_output_type(self, output_name: str):
        """
        Get the type of a specific output.
        
        Args:
            output_name: The output name
            
        Returns:
            The TensorGroupType for that output
        """
        if output_name not in self._target_module._outputs:
            raise ValueError(
                f"Output '{output_name}' not found in connected module '{self.name}'. "
                f"Available outputs: {list(self._target_module._outputs.keys())}"
            )
        return self._target_module._outputs[output_name]
    
    def _collect_leaf_retargeters(self, module) -> None:
        """Recursively collect leaf retargeters from a module."""
        if isinstance(module, ConnectedModule):
            # Compound: collect from its leaves
            for leaf_name, leaf_module in module._leaf_retargeters.items():
                if leaf_name not in self._leaf_retargeters:
                    self._leaf_retargeters[leaf_name] = leaf_module
        else:
            # Base retargeter: it's a leaf
            if module.name not in self._leaf_retargeters:
                self._leaf_retargeters[module.name] = module
    
    def __call__(self, inputs: Dict[str, TensorGroup] = None) -> Dict[str, TensorGroup]:
        """
        Execute the connected module with caching for shared sources.
        
        Args:
            inputs: Dict[retargeter_name, TensorGroup] - inputs for leaf retargeters
        
        Returns:
            Dict[output_name, TensorGroup] - flattened outputs from target module
        """
        if inputs is None:
            inputs = {}
        
        context = ExecutionContext()
        
        # Pre-allocate outputs
        outputs = {
            name: TensorGroup(group_type)
            for name, group_type in self._target_module._outputs.items()
        }
        
        self._compute_with_context(inputs, outputs, context)
        return outputs
    
    def _compute_with_context(
        self,
        inputs: Dict[str, TensorGroup],
        outputs: Dict[str, TensorGroup],
        context: ExecutionContext
    ) -> None:
        """Execute with a shared context for caching across nested ConnectedModules."""
        
        def execute_retargeter(retargeter: BaseRetargeter, output_name: str) -> TensorGroup:
            """
            Execute a retargeter and return a specific output.
            Uses caching to avoid redundant computation.
            """
            # Check cache first
            if context.has_cached(retargeter):
                cached_outputs = context.get_cached(retargeter)
                return cached_outputs[output_name]
            
            # Execute based on retargeter type
            if isinstance(retargeter, ConnectedModule):
                # Nested ConnectedModule: prepare its inputs and execute with shared context
                module_inputs = {}
                for leaf_name, leaf_module in retargeter._leaf_retargeters.items():
                    if leaf_name in inputs:
                        module_inputs[leaf_name] = inputs[leaf_name]
                
                # Pre-allocate outputs
                module_outputs = {
                    out_name: TensorGroup(out_type)
                    for out_name, out_type in retargeter._target_module._outputs.items()
                }
                
                # Execute with shared context
                retargeter._compute_with_context(module_inputs, module_outputs, context)
                
                # Cache all outputs
                context.cache(retargeter, module_outputs)
                
                # Return the specific output requested
                return module_outputs[output_name]
            else:
                # Base retargeter
                if len(retargeter._inputs) > 0:
                    # Has inputs - get them from the inputs dict
                    module_inputs = inputs.get(retargeter.name, {})
                else:
                    # No inputs - it's a source
                    module_inputs = {}
                
                # Execute
                module_outputs = retargeter(**module_inputs)
                
                # Cache all outputs
                context.cache(retargeter, module_outputs)
                
                return module_outputs[output_name]
        
        # Gather inputs for the target module
        target_inputs = {}
        for target_input_name, selector in self._connections.items():
            # Execute the source module and get the specific output
            output_tensor_group = execute_retargeter(
                selector.module,
                selector.output_name
            )
            target_inputs[target_input_name] = output_tensor_group
        
        # Execute target module
        target_outputs = self._target_module(**target_inputs)
        
        # Copy to outputs dict (flattened, no nesting)
        for output_name, tensor_group in target_outputs.items():
            outputs[output_name] = tensor_group
