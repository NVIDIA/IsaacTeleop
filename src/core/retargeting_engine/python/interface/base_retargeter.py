# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Retargeting module interfaces and base classes.

Defines the common API for retargeting modules with flat (unkeyed) outputs.
"""

from abc import ABC, abstractmethod
from typing import Dict, TYPE_CHECKING
from .tensor_group_type import TensorGroupType
from .tensor_group import TensorGroup
from .tensor import UNSET_VALUE
from .retargeter_core_types import OutputSelector, RetargeterIO, ExecutionContext, GraphExecutable, BaseExecutable, RetargeterIOType
from .retargeter_subgraph import RetargeterSubgraph


class BaseRetargeter(BaseExecutable, GraphExecutable):
    """
    Abstract base class for base retargeting modules.
    
    A base retargeter defines:
    - Input tensor collections: Dict[str, TensorGroupType] (unkeyed - by input name)
    - Output tensor collections: Dict[str, TensorGroupType] (unkeyed - by output name)
    - Compute logic that transforms inputs to outputs
    
    Base retargeters can be composed using connect() to create ConnectedModules.
    """

    def __init__(self, name: str) -> None:
        """
        Initialize a base retargeter.
        
        Args:
            name: Name identifier for this retargeter.
        """
        self._name = name
        self._inputs: RetargeterIOType = self.input_spec()
        self._outputs: RetargeterIOType = self.output_spec()

    @abstractmethod
    def input_spec(self) -> RetargeterIOType:
        """
        Define input tensor collections.
        
        Returns a dictionary mapping input names to TensorGroupType.
        
        Returns:
            Dict[str, TensorGroupType] - Input specification
        """
        pass

    @abstractmethod
    def output_spec(self) -> RetargeterIOType:
        """
        Define output tensor collections.
        
        Returns a dictionary mapping output names to TensorGroupType.
        
        Returns:
            Dict[str, TensorGroupType] - Output specification
        """
        pass

    @abstractmethod
    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Execute retargeting computation.

        This is the core method that transforms inputs to outputs.

        Args:
            inputs: Input tensor groups (Dict[str, TensorGroup])
            outputs: Output tensor groups to populate (Dict[str, TensorGroup])
        """
        pass

    def output_types(self) -> RetargeterIOType:
        """
        Return the output type specification for this retargeter.
        
        Returns:
            Dict[str, TensorGroupType] - Output type specification
        """
        return self._outputs

    def connect(self, input_connections: Dict[str, OutputSelector]) -> RetargeterSubgraph:
        """
        Connect this retargeter's inputs to outputs from other retargeters.
        
        Args:
            connections: Dict mapping this retargeter's input names to OutputSelectors
        
        Returns:
            A ConnectedModule (compound retargeter)
            
        Example:
            processor.connect({
                "left_hand": source.output("left"),
                "right_hand": right.output("pose")
            })
        """
        
        # Validate that all inputs are provided
        if set(input_connections.keys()) != set(self._inputs.keys()):
            missing = set(self._inputs.keys()) - set(input_connections.keys())
            extra = set(input_connections.keys()) - set(self._inputs.keys())
            msg = []
            if missing:
                msg.append(f"Missing inputs: {missing}")
            if extra:
                msg.append(f"Extra inputs: {extra}")
            raise ValueError(f"Input mismatch for {self._name}: {', '.join(msg)}")
        
        # Validate types
        for input_name, output_selector in input_connections.items():
            expected_type = self._inputs[input_name]
            actual_type = output_selector.module.output_types()[output_selector.output_name]
            # Throws error if types are not compatible.
            expected_type.check_compatibility(actual_type)
            
        
        return RetargeterSubgraph(
            target_module=self,
            input_connections=input_connections,
            output_types=self._outputs
        )

    def _validate_inputs(self, inputs: RetargeterIO) -> None:
        """
        Validate the inputs to the retargeter.
        
        Args:
            inputs: The inputs to the retargeter
        """
        if set(inputs.keys()) != set(self._inputs.keys()):
            raise ValueError(f"Expected inputs {set(self._inputs.keys())}, got {set(inputs.keys())}")

        for name, input_group in inputs.items():
            expected_type = self._inputs[name]
            actual_type = input_group.group_type
            # Throws error if types are not compatible.
            expected_type.check_compatibility(actual_type)

    # implements GraphExecutable interface.
    def _compute_in_graph(self, context: ExecutionContext) -> RetargeterIO:
        """
        Compute the retargeter in a graph context.
        
        Args:
            context: The execution context
        """
        # Check cache first
        outputs = context.get_cached(id(self))
        if outputs is not None:
            return outputs

        # Get inputs from context (if any are needed)
        if len(self._inputs) > 0:  # Only look for inputs if this module has any
            inputs = context.get_leaf_input(self._name)
            if inputs is None:
                raise ValueError(f"Input '{self._name}' not found in context")
        else:
            # Source modules with no inputs use empty dict
            inputs = {}

        # Create output tensor groups.
        outputs = {
            name: TensorGroup(group_type)
            for name, group_type in self._outputs.items()
        }

        # Execute compute and cache the results.
        self._validate_inputs(inputs)
        self.compute(inputs, outputs)
        context.cache(id(self), outputs)
        return outputs
    
    # implements BaseExecutable interface.
    def _compute_without_context(self, inputs: RetargeterIO) -> RetargeterIO:
        """
        Execute the retargeter as a callable (for running outside of a graph context).
        
        Args:
            **inputs: Input tensor groups as keyword arguments matching input names
            
        Returns:
            Dict[str, TensorGroup] - Output tensor groups
        """
        self._validate_inputs(inputs)
        
        # Create output tensor groups.
        outputs = {
            name: TensorGroup(group_type)
            for name, group_type in self._outputs.items()
        }
        
        # Execute compute
        self.compute(inputs, outputs)
        
        return outputs

    # For end-user convenience to invoke the retargeter as a callable.
    def __call__(self, inputs: RetargeterIO) -> RetargeterIO:
        return self._compute_without_context(inputs)
