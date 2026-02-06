# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for NDArray tensor types using NumPy as the DLPack-compatible framework.
"""

import pytest
import numpy as np
from isaacteleop.retargeting_engine.tensor_types import NDArrayType, DLDataType, DLDeviceType


def test_ndarray_type_creation():
    """Test creating NDArrayType with various configurations."""
    # Vector type
    vec3_type = NDArrayType(
        "position",
        shape=(3,),
        dtype=DLDataType.FLOAT,
        dtype_bits=32,
        device_type=DLDeviceType.CPU,
        device_id=0
    )
    
    assert vec3_type.name == "position"
    assert vec3_type.shape == (3,)
    assert vec3_type.dtype == DLDataType.FLOAT
    assert vec3_type.dtype_bits == 32
    assert vec3_type.device_type == DLDeviceType.CPU
    assert vec3_type.device_id == 0
    
    # Matrix type
    matrix_type = NDArrayType(
        "transform",
        shape=(3, 4),
        dtype=DLDataType.FLOAT,
        dtype_bits=32
    )
    
    assert matrix_type.shape == (3, 4)
    assert matrix_type.dtype == DLDataType.FLOAT
    
    # Integer array type
    int_array = NDArrayType(
        "indices",
        shape=(10,),
        dtype=DLDataType.INT,
        dtype_bits=32
    )
    
    assert int_array.dtype == DLDataType.INT
    assert int_array.dtype_bits == 32


def test_ndarray_type_compatibility():
    """Test NDArrayType compatibility checking."""
    # Same specifications - should be compatible
    type1 = NDArrayType("pos", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
    type2 = NDArrayType("vel", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
    
    assert type1.is_compatible_with(type2)
    
    # Different shape - not compatible
    type3 = NDArrayType("quat", shape=(4,), dtype=DLDataType.FLOAT, dtype_bits=32)
    assert not type1.is_compatible_with(type3)
    
    # Different dtype - not compatible
    type4 = NDArrayType("int_vec", shape=(3,), dtype=DLDataType.INT, dtype_bits=32)
    assert not type1.is_compatible_with(type4)
    
    # Different dtype bits - not compatible
    type5 = NDArrayType("pos64", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=64)
    assert not type1.is_compatible_with(type5)
    
    # Different device - not compatible
    type6 = NDArrayType(
        "pos_gpu",
        shape=(3,),
        dtype=DLDataType.FLOAT,
        dtype_bits=32,
        device_type=DLDeviceType.CUDA
    )
    assert not type1.is_compatible_with(type6)


def test_ndarray_validate_numpy_float32():
    """Test validation with NumPy float32 arrays."""
    vec3_type = NDArrayType("pos", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
    
    # Valid array - should not raise
    valid_array = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    vec3_type.validate_value(valid_array)
    
    # Wrong shape - should raise
    wrong_shape = np.array([1.0, 2.0], dtype=np.float32)
    with pytest.raises(TypeError, match="shape mismatch"):
        vec3_type.validate_value(wrong_shape)
    
    # Wrong dtype - should raise
    wrong_dtype = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    with pytest.raises(TypeError, match="dtype"):
        vec3_type.validate_value(wrong_dtype)
    
    # Not an array - should raise
    with pytest.raises(TypeError):
        vec3_type.validate_value([1.0, 2.0, 3.0])
    with pytest.raises(TypeError):
        vec3_type.validate_value("not an array")


def test_ndarray_validate_numpy_int32():
    """Test validation with NumPy int32 arrays."""
    int_array_type = NDArrayType("indices", shape=(5,), dtype=DLDataType.INT, dtype_bits=32)
    
    # Valid array - should not raise
    valid_array = np.array([1, 2, 3, 4, 5], dtype=np.int32)
    int_array_type.validate_value(valid_array)
    
    # Wrong dtype (int64) - should raise
    wrong_dtype = np.array([1, 2, 3, 4, 5], dtype=np.int64)
    with pytest.raises(TypeError, match="dtype"):
        int_array_type.validate_value(wrong_dtype)


def test_ndarray_validate_numpy_uint8():
    """Test validation with NumPy uint8 arrays (used for bool arrays)."""
    bool_array_type = NDArrayType("flags", shape=(10,), dtype=DLDataType.UINT, dtype_bits=8)
    
    # Valid array - should not raise
    valid_array = np.array([1, 0, 1, 0, 1, 0, 1, 0, 1, 0], dtype=np.uint8)
    bool_array_type.validate_value(valid_array)
    
    # Wrong dtype bits - should raise
    wrong_bits = np.array([1, 0, 1, 0, 1, 0, 1, 0, 1, 0], dtype=np.uint16)
    with pytest.raises(TypeError):
        bool_array_type.validate_value(wrong_bits)


def test_ndarray_validate_matrix():
    """Test validation with 2D NumPy arrays."""
    matrix_type = NDArrayType("transform", shape=(3, 4), dtype=DLDataType.FLOAT, dtype_bits=32)
    
    # Valid matrix - should not raise
    valid_matrix = np.zeros((3, 4), dtype=np.float32)
    matrix_type.validate_value(valid_matrix)
    
    # Wrong shape (transposed) - should raise
    wrong_shape = np.zeros((4, 3), dtype=np.float32)
    with pytest.raises(TypeError, match="shape mismatch"):
        matrix_type.validate_value(wrong_shape)
    
    # 1D array - should raise
    flat_array = np.zeros(12, dtype=np.float32)
    with pytest.raises(TypeError, match="shape mismatch"):
        matrix_type.validate_value(flat_array)


def test_ndarray_validation_error_messages():
    """Test that validation error messages are informative."""
    vec3_type = NDArrayType("pos", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
    
    # Wrong shape - should raise with informative message
    wrong_shape = np.array([1.0, 2.0], dtype=np.float32)
    with pytest.raises(TypeError) as exc_info:
        vec3_type.validate_value(wrong_shape)
    error_msg = str(exc_info.value)
    assert "shape mismatch" in error_msg
    assert "(3,)" in error_msg
    assert "(2,)" in error_msg
    
    # Wrong dtype - should raise with informative message
    wrong_dtype = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    with pytest.raises(TypeError) as exc_info:
        vec3_type.validate_value(wrong_dtype)
    error_msg = str(exc_info.value)
    assert "dtype bits mismatch" in error_msg
    assert "32" in error_msg
    assert "64" in error_msg
    
    # Not a DLPack object - should raise with informative message
    not_dlpack = [1.0, 2.0, 3.0]
    with pytest.raises(TypeError) as exc_info:
        vec3_type.validate_value(not_dlpack)
    error_msg = str(exc_info.value)
    assert "DLPack protocol" in error_msg


def test_ndarray_dlpack_device_types():
    """Test that device type enums are correct."""
    assert DLDeviceType.CPU == 1
    assert DLDeviceType.CUDA == 2
    assert DLDeviceType.CPU_PINNED == 3
    assert DLDeviceType.OPENCL == 4
    assert DLDeviceType.VULKAN == 7
    assert DLDeviceType.METAL == 8
    assert DLDeviceType.VPI == 9
    assert DLDeviceType.ROCM == 10


def test_ndarray_dlpack_data_types():
    """Test that data type enums are correct."""
    assert DLDataType.INT == 0
    assert DLDataType.UINT == 1
    assert DLDataType.FLOAT == 2
    assert DLDataType.BFLOAT == 4


def test_ndarray_names_preserved():
    """Test that tensor names are preserved in NDArrayType."""
    type1 = NDArrayType("position", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
    type2 = NDArrayType("velocity", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
    type3 = NDArrayType("acceleration", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
    
    assert type1.name == "position"
    assert type2.name == "velocity"
    assert type3.name == "acceleration"
    
    # Names don't affect compatibility
    assert type1.is_compatible_with(type2)
    assert type2.is_compatible_with(type3)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

