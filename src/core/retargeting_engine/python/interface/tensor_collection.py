"""
Tensor Collection for type metadata.

A TensorCollection defines the types and structure of a group of tensors,
used for building compute graphs.
"""

from typing import Dict, List, Optional
from .tensor_type import TensorType


class TensorCollection:
    """
    Defines the type metadata for a collection of tensors.
    
    Used for building compute graphs. Does not hold actual data.
    Tensors are stored as a list and accessed by name.
    """
    
    def __init__(self, name: str, tensors: List[TensorType]) -> None:
        """
        Initialize a tensor collection.
        
        Args:
            name: Name for this collection
            tensors: List of tensor types.
        """
        self._name = name
        self._types: List[TensorType] = list(tensors)
    
    @property
    def name(self) -> str:
        """Get the name of this collection."""
        return self._name
    
    def __len__(self) -> int:
        """Get the number of tensors in the collection."""
        return len(self._types)
    
    def is_compatible_with(self, other: 'TensorCollection') -> bool:
        """
        Check if this collection is type-compatible with another.
        
        Two collections are compatible if they have the same number of tensors
        and each tensor type is compatible at the corresponding position.
        
        Args:
            other: Another TensorCollection to check compatibility with
        
        Returns:
            True if collections are compatible, False otherwise
        """
        # Must have same number of tensors
        if len(self) != len(other):
            return False
        
        # Each tensor must be compatible by name
        for i, tensor_type in enumerate(self._types):
            other_type = other._types[i]
            if not tensor_type.is_compatible_with(other_type):
                return False
        
        return True
    
    def get_incompatibility_reason(self, other: 'TensorCollection') -> Optional[str]:
        """
        Get a detailed reason why two collections are incompatible.
        
        Args:
            other: Another TensorCollection to check
        
        Returns:
            A string describing the incompatibility, or None if compatible
        """
        # Check length
        if len(self) != len(other):
            return (
                f"Collection size mismatch: expected {len(self)} tensors, "
                f"got {len(other)} tensors"
            )
        
        # Check each tensor
        for i, tensor_type in enumerate(self._types):
            other_type = other._types[i]
            
            if not tensor_type.is_compatible_with(other_type):
                return (
                    f"Tensor {i} type mismatch: "
                    f"expected {tensor_type.__class__.__name__} ('{tensor_type.name}'), "
                    f"got {other_type.__class__.__name__} ('{other_type.name}')"
                )
        
        return None
    
    def __repr__(self) -> str:
        tensor_list = ", ".join(
            f"{t.name}:{t.__class__.__name__}"
            for t in self._types
        )
        return f"TensorCollection({len(self)} types: {tensor_list})"


