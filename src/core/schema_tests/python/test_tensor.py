# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TensorT and related types in isaacteleop.schema."""

import numpy as np

from isaacteleop.schema import (
    TensorT,
    DLDataType,
    DLDataTypeCode,
    DLDevice,
    DLDeviceType,
)


class TestDLDataTypeCode:
    """Tests for DLDataTypeCode enum."""

    def test_enum_values_exist(self):
        """Verify all expected enum values are accessible."""
        assert DLDataTypeCode.kDLInt is not None
        assert DLDataTypeCode.kDLUInt is not None
        assert DLDataTypeCode.kDLFloat is not None

    def test_enum_values_are_distinct(self):
        """Verify enum values are distinct."""
        values = {DLDataTypeCode.kDLInt, DLDataTypeCode.kDLUInt, DLDataTypeCode.kDLFloat}
        assert len(values) == 3


class TestDLDeviceType:
    """Tests for DLDeviceType enum."""

    def test_enum_values_exist(self):
        """Verify all expected enum values are accessible."""
        assert DLDeviceType.kDLUnknown is not None
        assert DLDeviceType.kDLCPU is not None
        assert DLDeviceType.kDLCUDA is not None
        assert DLDeviceType.kDLCUDAHost is not None
        assert DLDeviceType.kDLCUDAManaged is not None


class TestDLDataType:
    """Tests for DLDataType struct."""

    def test_default_constructor(self):
        """Test default construction."""
        dtype = DLDataType()
        assert dtype is not None

    def test_parameterized_constructor(self):
        """Test construction with parameters."""
        dtype = DLDataType(DLDataTypeCode.kDLFloat, 32, 1)
        assert dtype.code == DLDataTypeCode.kDLFloat
        assert dtype.bits == 32
        assert dtype.lanes == 1

    def test_int32_dtype(self):
        """Test int32 data type."""
        dtype = DLDataType(DLDataTypeCode.kDLInt, 32, 1)
        assert dtype.code == DLDataTypeCode.kDLInt
        assert dtype.bits == 32

    def test_float64_dtype(self):
        """Test float64 data type."""
        dtype = DLDataType(DLDataTypeCode.kDLFloat, 64, 1)
        assert dtype.code == DLDataTypeCode.kDLFloat
        assert dtype.bits == 64

    def test_uint8_dtype(self):
        """Test uint8 data type."""
        dtype = DLDataType(DLDataTypeCode.kDLUInt, 8, 1)
        assert dtype.code == DLDataTypeCode.kDLUInt
        assert dtype.bits == 8


class TestDLDevice:
    """Tests for DLDevice struct."""

    def test_default_constructor(self):
        """Test default construction."""
        device = DLDevice()
        assert device is not None

    def test_cpu_device(self):
        """Test CPU device creation."""
        device = DLDevice(DLDeviceType.kDLCPU, 0)
        assert device.device_type == DLDeviceType.kDLCPU
        assert device.device_id == 0

    def test_cuda_device(self):
        """Test CUDA device creation."""
        device = DLDevice(DLDeviceType.kDLCUDA, 1)
        assert device.device_type == DLDeviceType.kDLCUDA
        assert device.device_id == 1


class TestTensorTConstruction:
    """Tests for TensorT construction."""

    def test_default_constructor(self):
        """Test default construction creates empty tensor."""
        tensor = TensorT()
        assert tensor is not None

    def test_from_numpy_float32(self, float32_array):
        """Test creating TensorT from float32 numpy array."""
        tensor = TensorT.from_numpy(float32_array)
        assert tensor is not None
        assert tensor.ndim == 2
        assert list(tensor.shape) == [2, 3]
        assert tensor.dtype.code == DLDataTypeCode.kDLFloat
        assert tensor.dtype.bits == 32

    def test_from_numpy_float64(self, float64_array):
        """Test creating TensorT from float64 numpy array."""
        tensor = TensorT.from_numpy(float64_array)
        assert tensor is not None
        assert tensor.ndim == 1
        assert list(tensor.shape) == [4]
        assert tensor.dtype.code == DLDataTypeCode.kDLFloat
        assert tensor.dtype.bits == 64

    def test_from_numpy_int32(self, int32_array):
        """Test creating TensorT from int32 numpy array."""
        tensor = TensorT.from_numpy(int32_array)
        assert tensor is not None
        assert tensor.ndim == 1
        assert list(tensor.shape) == [5]
        assert tensor.dtype.code == DLDataTypeCode.kDLInt
        assert tensor.dtype.bits == 32

    def test_from_numpy_int64(self, int64_array):
        """Test creating TensorT from int64 numpy array."""
        tensor = TensorT.from_numpy(int64_array)
        assert tensor is not None
        assert tensor.ndim == 2
        assert list(tensor.shape) == [2, 2]
        assert tensor.dtype.code == DLDataTypeCode.kDLInt
        assert tensor.dtype.bits == 64

    def test_from_numpy_uint8(self, uint8_array):
        """Test creating TensorT from uint8 numpy array."""
        tensor = TensorT.from_numpy(uint8_array)
        assert tensor is not None
        assert tensor.ndim == 1
        assert list(tensor.shape) == [3]
        assert tensor.dtype.code == DLDataTypeCode.kDLUInt
        assert tensor.dtype.bits == 8

    def test_from_numpy_uint32(self, uint32_array):
        """Test creating TensorT from uint32 numpy array."""
        tensor = TensorT.from_numpy(uint32_array)
        assert tensor is not None
        assert tensor.ndim == 1
        assert list(tensor.shape) == [4]
        assert tensor.dtype.code == DLDataTypeCode.kDLUInt
        assert tensor.dtype.bits == 32


class TestTensorTRoundTrip:
    """Tests for TensorT numpy round-trip conversion."""

    def test_roundtrip_float32(self, float32_array):
        """Test float32 array survives round-trip conversion."""
        tensor = TensorT.from_numpy(float32_array)
        result = tensor.to_numpy()
        np.testing.assert_array_equal(result, float32_array)
        assert result.dtype == np.float32

    def test_roundtrip_float64(self, float64_array):
        """Test float64 array survives round-trip conversion."""
        tensor = TensorT.from_numpy(float64_array)
        result = tensor.to_numpy()
        np.testing.assert_array_equal(result, float64_array)
        assert result.dtype == np.float64

    def test_roundtrip_int32(self, int32_array):
        """Test int32 array survives round-trip conversion."""
        tensor = TensorT.from_numpy(int32_array)
        result = tensor.to_numpy()
        np.testing.assert_array_equal(result, int32_array)
        assert result.dtype == np.int32

    def test_roundtrip_int64(self, int64_array):
        """Test int64 array survives round-trip conversion."""
        tensor = TensorT.from_numpy(int64_array)
        result = tensor.to_numpy()
        np.testing.assert_array_equal(result, int64_array)
        assert result.dtype == np.int64

    def test_roundtrip_uint8(self, uint8_array):
        """Test uint8 array survives round-trip conversion."""
        tensor = TensorT.from_numpy(uint8_array)
        result = tensor.to_numpy()
        np.testing.assert_array_equal(result, uint8_array)
        assert result.dtype == np.uint8

    def test_roundtrip_uint32(self, uint32_array):
        """Test uint32 array survives round-trip conversion."""
        tensor = TensorT.from_numpy(uint32_array)
        result = tensor.to_numpy()
        np.testing.assert_array_equal(result, uint32_array)
        assert result.dtype == np.uint32

    def test_roundtrip_multidimensional(self):
        """Test multidimensional array survives round-trip."""
        original = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
        tensor = TensorT.from_numpy(original)
        result = tensor.to_numpy()
        np.testing.assert_array_equal(result, original)
        assert result.shape == (2, 3, 4)


class TestTensorTProperties:
    """Tests for TensorT property access and modification."""

    def test_shape_property(self, float32_array):
        """Test shape property access."""
        tensor = TensorT.from_numpy(float32_array)
        assert list(tensor.shape) == [2, 3]

    def test_shape_modification(self):
        """Test shape can be modified."""
        tensor = TensorT()
        tensor.shape = [4, 5, 6]
        assert list(tensor.shape) == [4, 5, 6]

    def test_ndim_property(self, float32_array):
        """Test ndim property access."""
        tensor = TensorT.from_numpy(float32_array)
        assert tensor.ndim == 2

    def test_strides_property(self, float32_array):
        """Test strides property access."""
        tensor = TensorT.from_numpy(float32_array)
        # For C-contiguous float32 array of shape (2, 3):
        # strides should be (12, 4) in bytes (3*4=12 for first dim, 4 for second)
        strides = list(tensor.strides)
        assert len(strides) == 2
        assert strides[0] == 12  # 3 elements * 4 bytes
        assert strides[1] == 4   # 1 element * 4 bytes

    def test_dtype_property(self, float32_array):
        """Test dtype property access."""
        tensor = TensorT.from_numpy(float32_array)
        assert tensor.dtype.code == DLDataTypeCode.kDLFloat
        assert tensor.dtype.bits == 32
        assert tensor.dtype.lanes == 1

    def test_dtype_modification(self):
        """Test dtype can be modified."""
        tensor = TensorT()
        tensor.dtype = DLDataType(DLDataTypeCode.kDLInt, 64, 1)
        assert tensor.dtype.code == DLDataTypeCode.kDLInt
        assert tensor.dtype.bits == 64

    def test_device_property(self, float32_array):
        """Test device defaults to CPU."""
        tensor = TensorT.from_numpy(float32_array)
        assert tensor.device.device_type == DLDeviceType.kDLCPU
        assert tensor.device.device_id == 0

    def test_device_modification(self):
        """Test device can be modified."""
        tensor = TensorT()
        tensor.device = DLDevice(DLDeviceType.kDLCUDA, 1)
        assert tensor.device.device_type == DLDeviceType.kDLCUDA
        assert tensor.device.device_id == 1

    def test_data_property(self, float32_array):
        """Test data property returns bytes."""
        tensor = TensorT.from_numpy(float32_array)
        data = tensor.data
        assert isinstance(data, bytes)
        # 6 float32 values = 24 bytes
        assert len(data) == 24


class TestTensorTEdgeCases:
    """Tests for TensorT edge cases."""

    def test_scalar_array(self):
        """Test handling of 0-dimensional (scalar) array."""
        scalar = np.array(42.0, dtype=np.float32)
        tensor = TensorT.from_numpy(scalar)
        assert tensor.ndim == 0
        assert list(tensor.shape) == []

    def test_empty_array(self):
        """Test handling of empty array."""
        empty = np.array([], dtype=np.float32)
        tensor = TensorT.from_numpy(empty)
        assert tensor.ndim == 1
        assert list(tensor.shape) == [0]

    def test_large_array(self):
        """Test handling of larger arrays."""
        large = np.random.randn(100, 100).astype(np.float32)
        tensor = TensorT.from_numpy(large)
        result = tensor.to_numpy()
        np.testing.assert_array_almost_equal(result, large)

    def test_non_contiguous_array(self):
        """Test handling of non-contiguous array."""
        original = np.arange(12, dtype=np.float32).reshape(3, 4)
        non_contiguous = original[::2, ::2]  # Every other element
        assert not non_contiguous.flags['C_CONTIGUOUS']

        tensor = TensorT.from_numpy(non_contiguous)
        result = tensor.to_numpy()
        np.testing.assert_array_equal(result, non_contiguous)

