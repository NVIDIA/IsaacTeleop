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
from .tensor import UNSET_VALUE, is_runtime_validation_enabled

if TYPE_CHECKING:
    from .connected_module import ConnectedModule

# Type alias for retargeter I/O (for a single base retargeter)
RetargeterIO = Dict[str, TensorGroupType]


class OutputSelector:
    """
    A reference to a specific named output of a retargeting module.
    
    Can be used with any RetargetingModule (modules with flat outputs).
    """
    
    def __init__(self, module: 'RetargetingModule', output_name: str):
        """
        Create an output selector.
        
        Args:
            module: The source retargeting module (any RetargetingModule)
            output_name: The name of the output
        """
        self.module = module
        self.output_name = output_name
    
    def __repr__(self) -> str:
        return f"{self.module.name}.outputs['{self.output_name}']"


class RetargetingModule(ABC):
    """
    Abstract base class for retargeting modules with flat (unkeyed) outputs.
    
    All modules inheriting from RetargetingModule return Dict[str, TensorGroup]
    where keys are output names (flat/unkeyed structure).
    
    Implementations:
    - BaseRetargeter: unkeyed inputs (**kwargs), unkeyed outputs
    - ConnectedModule: keyed inputs (Dict[retargeter_name, TensorGroup]), unkeyed outputs
    
    Common API:
    - name: Unique identifier
    - get_output_type(): Get type information for outputs
    - output(): Create OutputSelector for connecting modules
    
    Note: __call__() is NOT part of the common interface since BaseRetargeter
    and ConnectedModule have different input signatures.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of this retargeting module."""
        pass
    
    @abstractmethod
    def get_output_type(self, output_name: str) -> TensorGroupType:
        """
        Get the type of a specific output.
        
        Args:
            output_name: The output name
            
        Returns:
            The TensorGroupType for that output
            
        Raises:
            ValueError: If output_name is not found
        """
        pass
    
    def output(self, output_name: str) -> OutputSelector:
        """
        Get an OutputSelector for a specific output.
        
        This method is implemented in terms of get_output_type() to ensure
        the output exists before creating the selector.
        
        Args:
            output_name: The name of the output
            
        Returns:
            An OutputSelector instance
            
        Raises:
            ValueError: If output_name is not found
        """
        # Validate by calling get_output_type (which will raise if not found)
        self.get_output_type(output_name)
        return OutputSelector(self, output_name)
    
    def __repr__(self) -> str:
        """String representation showing class and name."""
        return f"{self.__class__.__name__}(name='{self.name}')"


class BaseRetargeter(RetargetingModule):
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
            name: Name identifier for this retargeter
        """
        self._name = name
        self._inputs: RetargeterIO = self.input_spec()
        self._outputs: RetargeterIO = self.output_spec()

    @property
    def name(self) -> str:
        """Get the name of this retargeter."""
        return self._name

    @abstractmethod
    def input_spec(self) -> RetargeterIO:
        """
        Define input tensor collections.
        
        Returns a dictionary mapping input names to TensorGroupType.
        
        Returns:
            Dict[str, TensorGroupType] - Input specification
        """
        pass

    @abstractmethod
    def output_spec(self) -> RetargeterIO:
        """
        Define output tensor collections.
        
        Returns a dictionary mapping output names to TensorGroupType.
        
        Returns:
            Dict[str, TensorGroupType] - Output specification
        """
        pass

    @abstractmethod
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Compute the transformation from inputs to outputs.
        
        Args:
            inputs: Dict[str, TensorGroup] - Input tensor groups
            outputs: Dict[str, TensorGroup] - Output tensor groups (pre-allocated, to be filled)
        """
        pass

    def connect(self, connections: Dict[str, OutputSelector]) -> 'ConnectedModule':
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
        from .connected_module import ConnectedModule
        
        # Validate that all inputs are provided
        if set(connections.keys()) != set(self._inputs.keys()):
            missing = set(self._inputs.keys()) - set(connections.keys())
            extra = set(connections.keys()) - set(self._inputs.keys())
            msg = []
            if missing:
                msg.append(f"Missing inputs: {missing}")
            if extra:
                msg.append(f"Extra inputs: {extra}")
            raise ValueError(f"Input mismatch for {self.name}: {', '.join(msg)}")
        
        # Validate types
        for input_name, selector in connections.items():
            expected_type = self._inputs[input_name]
            actual_type = selector.module.get_output_type(selector.output_name)
            
            try:
                expected_type.check_compatibility(actual_type)
            except ValueError as e:
                raise ValueError(
                    f"Type mismatch for input '{input_name}': {e}"
                )
        
        return ConnectedModule(
            name=f"{self.name}_connected",
            target_module=self,
            connections=connections
        )
    
    def get_output_type(self, output_name: str) -> TensorGroupType:
        """
        Get the type of a specific output.
        
        Args:
            output_name: The output name
            
        Returns:
            The TensorGroupType for that output
        """
        if output_name not in self._outputs:
            raise ValueError(
                f"Output '{output_name}' not found in retargeter '{self.name}'. "
                f"Available outputs: {list(self._outputs.keys())}"
            )
        return self._outputs[output_name]
    
    def __call__(self, **inputs: TensorGroup) -> Dict[str, TensorGroup]:
        """
        Execute the retargeter as a callable.
        
        Args:
            **inputs: Input tensor groups as keyword arguments matching input names
            
        Returns:
            Dict[str, TensorGroup] - Output tensor groups
        """
        if set(inputs.keys()) != set(self._inputs.keys()):
            raise ValueError(
                f"Expected inputs {set(self._inputs.keys())}, got {set(inputs.keys())}"
            )
        
        # Pre-allocate outputs
        outputs = {
            name: TensorGroup(group_type)
            for name, group_type in self._outputs.items()
        }
        
        # Execute compute
        self.compute(inputs, outputs)
        
        # Validate outputs were set
        if is_runtime_validation_enabled():
            for name, output_group in outputs.items():
                for i, tensor in enumerate(output_group._tensors):
                    if tensor.value is UNSET_VALUE:
                        raise ValueError(
                            f"Module '{self.name}' failed to set output tensor {i} "
                            f"in output '{name}'"
                        )
        
        return outputs

