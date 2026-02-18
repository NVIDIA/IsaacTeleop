# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for scalar tensor types.
"""

import pytest
from isaacteleop.retargeting_engine.tensor_types import FloatType, IntType, BoolType


def test_float_type():
    """Test FloatType."""
    float_type = FloatType("test_float")

    # Check name
    assert float_type.name == "test_float"

    # Check value validation - valid values should not raise
    float_type.validate_value(0.0)
    float_type.validate_value(3.14)
    float_type.validate_value(-1.5)

    # Invalid values should raise TypeError
    with pytest.raises(TypeError):
        float_type.validate_value(5)  # int
    with pytest.raises(TypeError):
        float_type.validate_value("hello")  # string


def test_int_type():
    """Test IntType."""
    int_type = IntType("test_int")

    # Check name
    assert int_type.name == "test_int"

    # Check value validation - valid values should not raise
    int_type.validate_value(0)
    int_type.validate_value(42)
    int_type.validate_value(-10)

    # Invalid values should raise TypeError
    with pytest.raises(TypeError):
        int_type.validate_value(3.14)  # float
    with pytest.raises(TypeError):
        int_type.validate_value("hello")  # string


def test_bool_type():
    """Test BoolType."""
    bool_type = BoolType("test_bool")

    # Check name
    assert bool_type.name == "test_bool"

    # Check value validation - valid values should not raise
    bool_type.validate_value(True)
    bool_type.validate_value(False)

    # Invalid values should raise TypeError
    with pytest.raises(TypeError):
        bool_type.validate_value(1)  # int
    with pytest.raises(TypeError):
        bool_type.validate_value(0.0)  # float
    with pytest.raises(TypeError):
        bool_type.validate_value("true")  # string


def test_scalar_type_compatibility():
    """Test that scalar types are compatible with same dtype."""
    int_type1 = IntType("int1")
    int_type2 = IntType("int2")
    float_type = FloatType("float1")
    bool_type = BoolType("bool1")

    # Same type should be compatible
    assert int_type1.is_compatible_with(int_type2)

    # Different types should not be compatible
    assert not int_type1.is_compatible_with(float_type)
    assert not float_type.is_compatible_with(bool_type)
    assert not bool_type.is_compatible_with(int_type1)


def test_scalar_type_names():
    """Test that tensor type names are preserved."""
    float_type = FloatType("velocity")
    int_type = IntType("count")
    bool_type = BoolType("is_active")

    assert float_type.name == "velocity"
    assert int_type.name == "count"
    assert bool_type.name == "is_active"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
