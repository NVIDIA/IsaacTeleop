# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""NDArray tensor type with DLPack support for framework interoperability."""

from typing import Any, Optional, Tuple
from enum import IntEnum
from ..interface.tensor_type import TensorType


class DLDataType(IntEnum):
    """DLPack data type codes."""
    INT = 0
    UINT = 1
    FLOAT = 2
    BFLOAT = 4


class DLDeviceType(IntEnum):
    """DLPack device type codes."""
    CPU = 1
    CUDA = 2
    CPU_PINNED = 3
    OPENCL = 4
    VULKAN = 7
    METAL = 8
    VPI = 9
    ROCM = 10


class NDArrayType(TensorType):
    """
    N-dimensional array tensor type with DLPack support.
    
    This type validates:
    - Array shape
    - Data type (via DLPack dtype)
    - Device type and ID
    
    Works with any framework that supports the DLPack protocol:
    - NumPy (via from_dlpack/to_dlpack)
    - PyTorch (via from_dlpack/to_dlpack)
    - JAX (via from_dlpack/to_dlpack)
    - CuPy, etc.
    """
    
    def __init__(
        self,
        name: str,
        shape: Tuple[int, ...],
        dtype: DLDataType = DLDataType.FLOAT,
        dtype_bits: int = 32,
        device_type: DLDeviceType = DLDeviceType.CPU,
        device_id: int = 0
    ) -> None:
        """
        Initialize an NDArray type.
        
        Args:
            name: Name for this tensor
            shape: Expected shape (e.g., (3, 4) for 3x4 matrix)
            dtype: DLPack data type (e.g., DLDataType.FLOAT)
            dtype_bits: Number of bits (e.g., 32 for float32)
            device_type: Device type (e.g., DLDeviceType.CPU, DLDeviceType.CUDA)
            device_id: Device ID (e.g., 0 for first GPU)
        """
        super().__init__(name)
        self._shape = shape
        self._dtype = dtype
        self._dtype_bits = dtype_bits
        self._device_type = device_type
        self._device_id = device_id
    
    @property
    def shape(self) -> Tuple[int, ...]:
        """Get the expected shape."""
        return self._shape
    
    @property
    def dtype(self) -> DLDataType:
        """Get the expected data type."""
        return self._dtype
    
    @property
    def dtype_bits(self) -> int:
        """Get the expected dtype bits."""
        return self._dtype_bits
    
    @property
    def device_type(self) -> DLDeviceType:
        """Get the expected device type."""
        return self._device_type
    
    @property
    def device_id(self) -> int:
        """Get the expected device ID."""
        return self._device_id
    
    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """Check if this NDArrayType is compatible with another."""
        assert isinstance(other, NDArrayType), f"Expected NDArrayType, got {type(other).__name__}"
        
        return (
            self._shape == other._shape and
            self._dtype == other._dtype and
            self._dtype_bits == other._dtype_bits and
            self._device_type == other._device_type and
            self._device_id == other._device_id
        )
    
    def _has_dlpack(self, value: Any) -> bool:
        """Check if value supports DLPack protocol."""
        return (
            hasattr(value, '__dlpack__') and
            hasattr(value, '__dlpack_device__')
        )
    
    def _get_dlpack_info(self, value: Any) -> Optional[Tuple]:
        """
        Get DLPack information from a value.
        
        Returns:
            Tuple of (shape, dtype_code, dtype_bits, device_type, device_id) or None
        """
        if not self._has_dlpack(value):
            return None
        
        try:
            # Get device info
            device = value.__dlpack_device__()
            device_type, device_id = device
            
            # Get tensor info from __dlpack__
            # We need to actually call from_dlpack to inspect it
            # But we can get shape and dtype from the object directly
            
            # Try NumPy-style attributes first
            if hasattr(value, 'shape') and hasattr(value, 'dtype'):
                shape = tuple(value.shape)
                
                # Map dtype to DLPack dtype
                dtype_str = str(value.dtype)
                if 'float32' in dtype_str or 'f4' in dtype_str:
                    dtype_code, dtype_bits = DLDataType.FLOAT, 32
                elif 'float64' in dtype_str or 'f8' in dtype_str:
                    dtype_code, dtype_bits = DLDataType.FLOAT, 64
                elif 'int32' in dtype_str or 'i4' in dtype_str:
                    dtype_code, dtype_bits = DLDataType.INT, 32
                elif 'int64' in dtype_str or 'i8' in dtype_str:
                    dtype_code, dtype_bits = DLDataType.INT, 64
                elif 'uint8' in dtype_str or 'u1' in dtype_str:
                    dtype_code, dtype_bits = DLDataType.UINT, 8
                else:
                    return None
                
                return (shape, dtype_code, dtype_bits, device_type, device_id)
            
            return None
        except Exception:
            return None
    
    def validate_value(self, value: Any) -> None:
        """
        Validate that value conforms to this NDArray type.
        
        Raises:
            TypeError: If value does not conform to the NDArray specifications
        """
        if not self._has_dlpack(value):
            raise TypeError(
                f"Value does not support DLPack protocol (__dlpack__ and __dlpack_device__) "
                f"for '{self.name}'. Got {type(value).__name__}"
            )
        
        info = self._get_dlpack_info(value)
        if info is None:
            raise TypeError(
                f"Could not extract DLPack information from value for '{self.name}'"
            )
        
        shape, dtype_code, dtype_bits, device_type, device_id = info
        
        errors = []
        if shape != self._shape:
            errors.append(f"shape mismatch: expected {self._shape}, got {shape}")
        
        if dtype_code != self._dtype:
            errors.append(
                f"dtype mismatch: expected {self._dtype.name}, got {DLDataType(dtype_code).name}"
            )
        
        if dtype_bits != self._dtype_bits:
            errors.append(f"dtype bits mismatch: expected {self._dtype_bits}, got {dtype_bits}")
        
        if device_type != self._device_type:
            errors.append(
                f"device type mismatch: expected {self._device_type.name}, got {DLDeviceType(device_type).name}"
            )
        
        if device_id != self._device_id:
            errors.append(f"device ID mismatch: expected {self._device_id}, got {device_id}")
        
        if errors:
            raise TypeError(f"Invalid NDArray for '{self.name}': {'; '.join(errors)}")

