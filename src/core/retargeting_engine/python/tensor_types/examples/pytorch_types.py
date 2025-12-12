"""
PyTorch tensor types for the retargeting engine.

Provides support for PyTorch tensors with dtype, shape, and device constraints.
Enables GPU-accelerated computations when available.
"""

from typing import Any, Optional, Tuple, Union
import torch
from ...interface.tensor_type import TensorType


class PyTorchTensorType(TensorType):
    """
    Represents PyTorch tensor types.
    
    Can be subclassed to create specific tensor types (e.g., Vector3Type, Matrix4x4Type).
    Compatibility is strict - dtype and shape must match exactly.
    Device is not checked for compatibility (tensors can be moved between devices).
    """
    
    def __init__(
        self, 
        name: str,
        dtype: Optional[torch.dtype] = None, 
        shape: Optional[Tuple[int, ...]] = None,
        device: Optional[Union[str, torch.device]] = None,
    ) -> None:
        """
        Initialize a PyTorch tensor type.
        
        Args:
            name: Name for this tensor type
            dtype: PyTorch dtype (e.g., torch.float32, torch.float64)
            shape: Shape tuple (required for strict compatibility)
            device: Device to allocate tensor on ('cpu', 'cuda', 'cuda:0', etc.)
                   Defaults to 'cpu' if not specified
        """
        self._dtype = dtype if dtype is not None else torch.float32
        self._shape = shape
        self._device = torch.device(device) if device is not None else torch.device('cpu')
        super().__init__(name)
    
    @property
    def dtype(self) -> torch.dtype:
        """Get the dtype of this tensor type."""
        return self._dtype
    
    @property
    def shape(self) -> Optional[Tuple[int, ...]]:
        """Get the shape of this tensor type."""
        return self._shape
    
    @property
    def device(self) -> torch.device:
        """Get the device of this tensor type."""
        return self._device

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """
        Check instance compatibility for PyTorch tensor types.
        
        Both dtype and shape must match exactly for compatibility.
        Device is NOT checked - tensors can be moved between devices.
        """
        if isinstance(other, PyTorchTensorType):
            # Exact dtype match required
            if self._dtype != other._dtype:
                return False
            
            # Exact shape match required
            if self._shape != other._shape:
                return False
            
            return True
        return False

    def allocate_default(self) -> Union[torch.Tensor, None]:
        """
        Allocate a default value for PyTorch tensor types.

        Returns:
            A PyTorch tensor filled with zeros if dtype and shape are specified,
            otherwise None
        """
        if self._dtype is not None and self._shape is not None:
            # Create tensor of zeros with specified dtype, shape, and device
            return torch.zeros(self._shape, dtype=self._dtype, device=self._device)
        else:
            # Cannot allocate without both dtype and shape
            return None
    
    def to(self, device: Union[str, torch.device]) -> 'PyTorchTensorType':
        """
        Create a new PyTorchTensorType with a different device.
        
        Args:
            device: Target device ('cpu', 'cuda', 'cuda:0', etc.)
            
        Returns:
            New PyTorchTensorType with the specified device
        """
        return PyTorchTensorType(
            name=self._name,
            dtype=self._dtype,
            shape=self._shape,
            device=device
        )
    
    def __repr__(self) -> str:
        return f"PyTorchTensorType(name='{self._name}', dtype={self._dtype}, shape={self._shape}, device={self._device})"

