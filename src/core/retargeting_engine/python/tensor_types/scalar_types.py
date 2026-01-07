# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Scalar tensor types (float, int, bool)."""

from typing import Any
from ..interface.tensor_type import TensorType


class FloatType(TensorType):
    """A floating-point scalar tensor type."""
    
    def __init__(self, name: str) -> None:
        """
        Initialize a float type.
        
        Args:
            name: Name for this tensor
        """
        super().__init__(name)
    
    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """Float types are always compatible with other float types."""
        assert isinstance(other, FloatType), f"Expected FloatType, got {type(other).__name__}"
        return True
    
    def validate_value(self, value: Any) -> None:
        """
        Validate if the given value is a float (and not a bool or int).
        
        Raises:
            TypeError: If value is not a float
        """
        if not isinstance(value, float) or isinstance(value, bool):
            raise TypeError(
                f"Expected float for '{self.name}', got {type(value).__name__}"
            )


class IntType(TensorType):
    """An integer scalar tensor type."""
    
    def __init__(self, name: str) -> None:
        """
        Initialize an int type.
        
        Args:
            name: Name for this tensor
        """
        super().__init__(name)
    
    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """Int types are always compatible with other int types."""
        assert isinstance(other, IntType), f"Expected IntType, got {type(other).__name__}"
        return True
    
    def validate_value(self, value: Any) -> None:
        """
        Validate if the given value is an int (and not a bool).
        
        Raises:
            TypeError: If value is not an int
        """
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(
                f"Expected int for '{self.name}', got {type(value).__name__}"
            )


class BoolType(TensorType):
    """A boolean scalar tensor type."""
    
    def __init__(self, name: str) -> None:
        """
        Initialize a bool type.
        
        Args:
            name: Name for this tensor
        """
        super().__init__(name)
    
    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """Bool types are always compatible with other bool types."""
        assert isinstance(other, BoolType), f"Expected BoolType, got {type(other).__name__}"
        return True
    
    def validate_value(self, value: Any) -> None:
        """
        Validate if the given value is a bool.
        
        Raises:
            TypeError: If value is not a bool
        """
        if not isinstance(value, bool):
            raise TypeError(
                f"Expected bool for '{self.name}', got {type(value).__name__}"
            )

