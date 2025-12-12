"""
Tensor Group for data storage.

A TensorGroup holds actual tensor data and references a TensorCollection for type metadata.
"""

from typing import List, Any, Iterator, Tuple
from .tensor_collection import TensorCollection
from .tensor import Tensor


class TensorGroup:
    """
    A group of tensors holding actual data.
    
    References a TensorCollection for type metadata.
    Provides indexed access to tensor data.
    """
    
    def __init__(self, collection: TensorCollection) -> None:
        """
        Initialize a tensor group from a collection definition.
        
        Args:
            collection: The TensorCollection defining the types
        """
        self._collection = collection
        self._tensors: List[Tensor] = []
        
        # Initialize tensors for each type in the collection
        for tensor_type in collection._types:
            self._tensors.append(Tensor(tensor_type=tensor_type))
    
    def get_tensor(self, index: int) -> Tensor:
        """
        Get the Tensor object by index.
        
        Args:
            index: Index of the tensor
            
        Returns:
            The Tensor object
            
        Raises:
            IndexError: If index is out of range
        """
        if index < 0 or index >= len(self._tensors):
            raise IndexError(f"Index {index} out of range [0, {len(self._tensors)})")
        
        return self._tensors[index]
    
    def __len__(self) -> int:
        """Get the number of tensors in the group."""
        return len(self._tensors)
    
    def __getitem__(self, index: int) -> Any:
        """
        Get a tensor value by index.
        
        Args:
            index: Integer index
            
        Returns:
            The tensor value
        """
        if index < 0 or index >= len(self._tensors):
            raise IndexError(f"Index {index} out of range [0, {len(self._tensors)})")
        return self._tensors[index].value
    
    def __setitem__(self, index: int, value: Any) -> None:
        """
        Set a tensor value by index.
        
        Args:
            index: Integer index
            value: New value for the tensor
        """
        if index < 0 or index >= len(self._tensors):
            raise IndexError(f"Index {index} out of range [0, {len(self._tensors)})")
        self._tensors[index].value = value
    
    def values(self) -> List[Any]:
        """Get all tensor values in order."""
        return [tensor.value for tensor in self._tensors]
    
    def tensors(self) -> List[Tensor]:
        """Get all Tensor objects in order."""
        return list(self._tensors)
    
    def __iter__(self) -> Iterator[Any]:
        """Iterate over tensor values."""
        return iter(tensor.value for tensor in self._tensors)
    
    def __repr__(self) -> str:
        return f"TensorGroup({len(self)} tensors)"

