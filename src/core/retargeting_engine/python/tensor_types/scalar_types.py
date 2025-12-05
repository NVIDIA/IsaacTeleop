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
        return True
    
    def validate_value(self, value: Any) -> bool:
        """Validate if the given value is a float (and not a bool or int)."""
        return isinstance(value, float) and not isinstance(value, bool)


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
        return True
    
    def validate_value(self, value: Any) -> bool:
        """Validate if the given value is an int (and not a bool)."""
        return isinstance(value, int) and not isinstance(value, bool)


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
        return True
    
    def validate_value(self, value: Any) -> bool:
        """Validate if the given value is a bool."""
        return isinstance(value, bool)

