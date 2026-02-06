# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for Tensor class - runtime data holder with type validation.
"""

import pytest
import numpy as np
from isaacteleop.retargeting_engine.interface import (
    Tensor,
    UNSET_VALUE,
)
from isaacteleop.retargeting_engine.tensor_types import (
    FloatType,
    IntType,
    BoolType,
    NDArrayType,
    DLDataType,
)


class TestTensorConstruction:
    """Test tensor construction and initialization."""

    def test_tensor_with_no_value(self):
        """Test creating a tensor without initial value."""
        float_type = FloatType("temperature")
        tensor = Tensor(float_type)
        
        # Should have UNSET_VALUE
        assert tensor._value is UNSET_VALUE
        assert tensor.tensor_type == float_type
        
        # Accessing value should raise
        with pytest.raises(ValueError, match="value has not been set"):
            _ = tensor.value

    def test_tensor_with_valid_value(self):
        """Test creating a tensor with valid initial value."""
        float_type = FloatType("temperature")
        tensor = Tensor(float_type, 25.5)
        
        assert tensor.value == 25.5
        assert tensor.tensor_type == float_type

    def test_tensor_with_invalid_value(self):
        """Test creating a tensor with invalid initial value."""
        float_type = FloatType("temperature")
        
        # Int should not validate for float type
        with pytest.raises(TypeError, match="Expected float for 'temperature'"):
            Tensor(float_type, 42)

    def test_tensor_with_none_uses_unset(self):
        """Test that passing None explicitly uses UNSET_VALUE."""
        int_type = IntType("count")
        tensor = Tensor(int_type, None)
        
        assert tensor._value is UNSET_VALUE
        with pytest.raises(ValueError, match="value has not been set"):
            _ = tensor.value


class TestTensorValueAccess:
    """Test tensor value getter and setter."""

    def test_get_value_after_set(self):
        """Test getting value after setting it."""
        int_type = IntType("count")
        tensor = Tensor(int_type)
        
        # Set value
        tensor.value = 42
        assert tensor.value == 42

    def test_set_value_validates_type(self):
        """Test that setting value validates against tensor type."""
        float_type = FloatType("velocity")
        tensor = Tensor(float_type, 0.0)
        
        # Valid value
        tensor.value = 3.14
        assert tensor.value == 3.14
        
        # Invalid value (int instead of float)
        with pytest.raises(TypeError, match="Expected float for 'velocity'"):
            tensor.value = 5

    def test_get_unset_value_raises(self):
        """Test that getting unset value raises ValueError."""
        bool_type = BoolType("flag")
        tensor = Tensor(bool_type)
        
        with pytest.raises(ValueError, match="value has not been set"):
            _ = tensor.value

    def test_value_update(self):
        """Test updating value multiple times."""
        float_type = FloatType("position")
        tensor = Tensor(float_type, 0.0)
        
        tensor.value = 1.0
        assert tensor.value == 1.0
        
        tensor.value = 2.5
        assert tensor.value == 2.5
        
        tensor.value = -3.14
        assert tensor.value == -3.14


class TestTensorWithNdArray:
    """Test tensor with numpy array types."""

    def test_tensor_with_ndarray(self, float32_array):
        """Test tensor holding numpy array."""
        array_type = NDArrayType("points", shape=(2, 3), dtype=DLDataType.FLOAT, dtype_bits=32)
        tensor = Tensor(array_type, float32_array)
        
        assert np.array_equal(tensor.value, float32_array)
        assert tensor.value.dtype == np.float32

    def test_tensor_ndarray_wrong_shape(self, float32_array):
        """Test that wrong shape is rejected."""
        array_type = NDArrayType("points", shape=(3, 3), dtype=DLDataType.FLOAT, dtype_bits=32)
        
        with pytest.raises(TypeError, match="shape mismatch"):
            Tensor(array_type, float32_array)

    def test_tensor_ndarray_wrong_dtype(self, int32_array):
        """Test that wrong dtype is rejected."""
        array_type = NDArrayType("data", shape=(5,), dtype=DLDataType.FLOAT, dtype_bits=32)
        
        with pytest.raises(TypeError, match="dtype mismatch"):
            Tensor(array_type, int32_array)

    def test_tensor_ndarray_set_new_array(self):
        """Test setting new numpy array value."""
        array_type = NDArrayType("matrix", shape=(2, 2), dtype=DLDataType.FLOAT, dtype_bits=32)
        
        arr1 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        tensor = Tensor(array_type, arr1)
        assert np.array_equal(tensor.value, arr1)
        
        arr2 = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)
        tensor.value = arr2
        assert np.array_equal(tensor.value, arr2)


class TestRuntimeValidation:
    """Test runtime validation behavior."""

    def test_runtime_validation_default_enabled(self):
        """Test that runtime validation is enabled by default."""
        assert Tensor.is_runtime_validation_enabled()

    def test_disable_runtime_validation(self):
        """Test disabling runtime validation."""
        original_state = Tensor.is_runtime_validation_enabled()
        
        try:
            Tensor.set_runtime_validation(False)
            assert not Tensor.is_runtime_validation_enabled()
            
            Tensor.set_runtime_validation(True)
            assert Tensor.is_runtime_validation_enabled()
        finally:
            # Restore original state
            Tensor.set_runtime_validation(original_state)

    def test_runtime_validation_on_get(self):
        """Test that runtime validation happens on value access."""
        float_type = FloatType("test")
        tensor = Tensor(float_type, 3.14)
        
        # Enable validation
        original_state = Tensor.is_runtime_validation_enabled()
        try:
            Tensor.set_runtime_validation(True)
            
            # Normal access should work
            assert tensor.value == 3.14
            
            # Corrupt the value directly (bypassing setter)
            tensor._value = "corrupted"
            
            # Now accessing should fail validation
            with pytest.raises(RuntimeError, match="Tensor value corrupted"):
                _ = tensor.value
        finally:
            Tensor.set_runtime_validation(original_state)

    def test_runtime_validation_disabled_no_check(self):
        """Test that disabling validation skips checks on get."""
        float_type = FloatType("test")
        tensor = Tensor(float_type, 3.14)
        
        original_state = Tensor.is_runtime_validation_enabled()
        try:
            Tensor.set_runtime_validation(False)
            
            # Corrupt the value
            tensor._value = "corrupted"
            
            # Should not raise since validation is disabled
            corrupted_value = tensor.value
            assert corrupted_value == "corrupted"
        finally:
            Tensor.set_runtime_validation(original_state)


class TestTensorRepr:
    """Test tensor string representation."""

    def test_tensor_repr_with_value(self):
        """Test repr with set value."""
        int_type = IntType("counter")
        tensor = Tensor(int_type, 42)
        
        repr_str = repr(tensor)
        assert repr_str == "Tensor(type=counter, value=42)"

    def test_tensor_repr_unset(self):
        """Test repr with unset value."""
        float_type = FloatType("position")
        tensor = Tensor(float_type)
        
        repr_str = repr(tensor)
        assert repr_str == "Tensor(type=position, value=<UNSET>)"


class TestTensorTypeProperty:
    """Test tensor_type property."""

    def test_tensor_type_property(self):
        """Test accessing tensor_type property."""
        bool_type = BoolType("active")
        tensor = Tensor(bool_type, True)
        
        assert tensor.tensor_type == bool_type
        assert tensor.tensor_type.name == "active"

    def test_tensor_type_immutable(self):
        """Test that tensor type cannot be changed after creation."""
        float_type = FloatType("temp")
        tensor = Tensor(float_type, 0.0)
        
        # tensor_type has no setter, should raise AttributeError
        with pytest.raises(AttributeError):
            tensor.tensor_type = IntType("other")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

