# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tensor Group Type for type metadata.

A TensorGroupType defines the types and structure of a group of tensors.
"""

from typing import List
from .tensor_type import TensorType


class TensorGroupType:
    """
    Defines the type metadata for a collection of tensors.
    
    Used for building compute graphs. Does not hold actual data.
    """
    
    def __init__(self, name: str, tensors: List[TensorType]) -> None:
        """
        Initialize a tensor group type.
        
        Args:
            name: Name for this group type
            tensors: List of tensor types.
        """
        self._name = name
        self._types: List[TensorType] = list(tensors)
    
    @property
    def name(self) -> str:
        """Get the name of this group type."""
        return self._name
    
    @property
    def types(self) -> List[TensorType]:
        """Get the list of tensor types."""
        return self._types
    
    def __len__(self) -> int:
        """Get the number of tensors in this group."""
        return len(self._types)
    
    def check_compatibility(self, other: 'TensorGroupType'):
        """
        Check if this group type is type-compatible with another.
        
        Two group types are compatible if they have the same number of tensors
        and each tensor type is compatible at the corresponding position.
        
        Args:
            other: Another TensorGroupType to check compatibility with
        
        Returns:
            True if group types are compatible, False otherwise
        """
        # Must have same number of tensors
        if len(self) != len(other):
            raise ValueError(
                f"Group type size mismatch: expected {len(self)} tensors, got {len(other)} tensors"
            )
        
        # Each tensor must be compatible
        for i, tensor_type in enumerate(self._types):
            other_type = other._types[i]
            if not tensor_type.is_compatible_with(other_type):
                raise ValueError(
                    f"Tensor {i} type mismatch: "
                    f"expected {tensor_type.__class__.__name__} ('{tensor_type.name}'), "
                    f"got {other_type.__class__.__name__} ('{other_type.name}')"
                )
    
    def __repr__(self) -> str:
        tensor_list = ", ".join(
            f"{t.name}:{t.__class__.__name__}"
            for t in self._types
        )
        return f"TensorGroupType({len(self)} types: {tensor_list})"

