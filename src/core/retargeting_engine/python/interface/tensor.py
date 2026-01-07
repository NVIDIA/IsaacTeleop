# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tensor - Holds actual tensor data with runtime type checking.

A Tensor object contains the runtime value of a tensor and its associated type
for validation.
"""

import os
from typing import Any, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .tensor_type import TensorType


# Sentinel value to indicate an unset tensor
class _UnsetValue:
    """Sentinel type for unset tensor values."""
    def __repr__(self) -> str:
        return "<UNSET>"

UNSET_VALUE = _UnsetValue()


class Tensor:
    """
    Holds the actual data for a tensor with runtime type checking.
    
    Can be initialized with None and later set with a valid value.
    Values are validated against the tensor type on assignment.
    """
    
    # Class-level flag to enable/disable runtime validation (for performance)
    _runtime_validation_enabled: bool = os.environ.get("RETARGETING_RUNTIME_VALIDATION", "1") == "1"
    
    @classmethod
    def set_runtime_validation(cls, enabled: bool) -> None:
        """
        Enable or disable runtime validation globally.
        
        Args:
            enabled: True to enable validation, False to disable for performance
        """
        cls._runtime_validation_enabled = enabled
    
    @classmethod
    def is_runtime_validation_enabled(cls) -> bool:
        """Check if runtime validation is currently enabled."""
        return cls._runtime_validation_enabled
    
    def __init__(self, tensor_type: 'TensorType', value: Any = None) -> None:
        """
        Initialize a tensor with a type and optional value.
        
        Args:
            tensor_type: The TensorType that defines what values are valid
            value: The actual tensor data (defaults to UNSET_VALUE if None)
            
        Raises:
            TypeError: If value is provided and doesn't match the tensor type
        """
        self._type = tensor_type
        self._value: Any = UNSET_VALUE if value is None else value
        
        # If value provided (not None), validate it
        if value is not None:
            tensor_type.validate_value(value)
    
    @property
    def value(self) -> Any:
        """
        Get the tensor value.
        
        If runtime validation is enabled, this will re-validate the value
        to catch any corruption or unexpected changes.
        """
        if self._value is UNSET_VALUE:
            raise ValueError(f"Tensor '{self._type.name}' value has not been set")
        
        if self._runtime_validation_enabled:
            try:
                self._type.validate_value(self._value)
            except TypeError as e:
                raise RuntimeError(
                    f"Tensor value corrupted for '{self._type.name}': {e}"
                ) from e
        return self._value
    
    @value.setter
    def value(self, new_value: Any) -> None:
        """
        Set the tensor value with validation.
        
        Args:
            new_value: The new value to set
            
        Raises:
            TypeError: If value doesn't match the tensor type
        """
        self._type.validate_value(new_value)
        self._value = new_value
    
    @property
    def tensor_type(self) -> 'TensorType':
        """Get the tensor's type."""
        return self._type
    
    def __repr__(self) -> str:
        return f"Tensor(type={self._type.name}, value={self._value})"

