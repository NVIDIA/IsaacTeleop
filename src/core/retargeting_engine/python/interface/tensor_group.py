# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tensor Group for data storage.

A TensorGroup holds actual tensor data and references a TensorGroupType for type metadata.
"""

from typing import List, Any
from .tensor_group_type import TensorGroupType
from .tensor import Tensor


class TensorGroup:
    """
    A group of tensors holding actual data.
    
    Associates tensors with their type metadata for validation.
    Provides indexed access to tensor values.
    
    Can be pre-allocated with None values for output caching.
    """
    
    def __init__(self, group_type: TensorGroupType) -> None:
        """
        Initialize a tensor group with pre-allocated tensors.
        
        Tensors are created with None values initially and must be set
        by the compute function.
        
        Args:
            group_type: The TensorGroupType defining the structure
        """
        self._group_type = group_type
        
        # Pre-allocate tensors with proper types but None values
        self._tensors: List[Tensor] = [
            Tensor(tensor_type) for tensor_type in group_type.types
        ]
    
    @property
    def group_type(self) -> TensorGroupType:
        """Get the associated group type."""
        return self._group_type

    def __len__(self) -> int:
        """Get the number of tensors in the group."""
        return len(self._tensors)
    
    def __getitem__(self, index: int) -> Any:
        """
        Get a tensor value by index.
        
        Args:
            index: Integer index
            
        Returns:
            The tensor value (with optional runtime validation)
            
        Raises:
            ValueError: If tensor value has not been set
        """
        return self._tensors[index].value
    
    def __setitem__(self, index: int, value: Any) -> None:
        """
        Set a tensor value by index.
        
        Args:
            index: Integer index
            value: The value to set (validated against tensor type)
            
        Raises:
            TypeError: If value doesn't validate against the tensor type
        """
        self._tensors[index].value = value
    
    def get_tensor(self, index: int) -> Tensor:
        """
        Get the Tensor object (not just the value) by index.
        
        This is useful if you need access to the tensor type or want to
        pass the tensor around without unwrapping.
        
        Args:
            index: Integer index
            
        Returns:
            The Tensor object
        """
        return self._tensors[index]
    
    def __repr__(self) -> str:
        return f"TensorGroup({self._group_type.name}, {len(self)} tensors)"

