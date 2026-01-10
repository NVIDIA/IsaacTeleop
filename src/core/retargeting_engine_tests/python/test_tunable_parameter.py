# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for tunable parameter specifications (immutable specs, not values)."""

import pytest
import numpy as np
from teleopcore.retargeting_engine.interface.tunable_parameter import (
    BoolParameter,
    FloatParameter,
    IntParameter,
    VectorParameter,
)


class TestBoolParameter:
    """Tests for BoolParameter specification."""
    
    def test_construction_with_defaults(self):
        """Test BoolParameter with default values."""
        param = BoolParameter(name="test_bool", description="A test bool")
        assert param.name == "test_bool"
        assert param.description == "A test bool"
        assert param.get_default_value() is False
        assert param.default_value is False
    
    def test_construction_with_custom_default(self):
        """Test BoolParameter with custom default value."""
        param = BoolParameter(name="enabled", description="Enable feature", default_value=True)
        assert param.get_default_value() is True
        assert param.default_value is True
    
    def test_validate(self):
        """Test bool parameter validation."""
        param = BoolParameter(name="flag", description="A flag")
        assert param.validate(True) is True
        assert param.validate(False) is True
        assert param.validate(1) is False
        assert param.validate("true") is False
    
    def test_serialization(self):
        """Test bool parameter serialization."""
        param = BoolParameter(name="flag", description="A flag", default_value=True)
        assert param.serialize(True) is True
        assert param.serialize(False) is False
    
    def test_deserialization(self):
        """Test bool parameter deserialization."""
        param = BoolParameter(name="flag", description="A flag")
        assert param.deserialize(True) is True
        assert param.deserialize(False) is False


class TestFloatParameter:
    """Tests for FloatParameter specification."""
    
    def test_construction_with_defaults(self):
        """Test FloatParameter with default values."""
        param = FloatParameter(name="scale", description="Scale factor")
        assert param.name == "scale"
        assert param.get_default_value() == 0.0
        assert param.min_value == -float('inf')
        assert param.max_value == float('inf')
        assert param.step_size == 0.01
    
    def test_construction_with_bounds(self):
        """Test FloatParameter with bounds."""
        param = FloatParameter(
            name="alpha",
            description="Alpha value",
            default_value=0.5,
            min_value=0.0,
            max_value=1.0,
            step_size=0.1
        )
        assert param.get_default_value() == 0.5
        assert param.min_value == 0.0
        assert param.max_value == 1.0
        assert param.step_size == 0.1
    
    def test_invalid_bounds(self):
        """Test that invalid bounds raise an error."""
        with pytest.raises(ValueError, match="min_value must be less than max_value"):
            FloatParameter(
                name="bad",
                description="Bad param",
                min_value=1.0,
                max_value=0.0
            )
    
    def test_validate(self):
        """Test float parameter validation."""
        param = FloatParameter(name="alpha", description="Alpha", min_value=0.0, max_value=1.0)
        assert param.validate(0.5) is True
        assert param.validate(0.0) is True
        assert param.validate(1.0) is True
        assert param.validate(-0.1) is False
        assert param.validate(1.1) is False
        assert param.validate("0.5") is False
    
    def test_serialization(self):
        """Test float parameter serialization."""
        param = FloatParameter(name="value", description="Value", default_value=3.14)
        assert param.serialize(3.14) == 3.14
        assert param.serialize(2.71) == 2.71
    
    def test_deserialization(self):
        """Test float parameter deserialization."""
        param = FloatParameter(name="value", description="Value")
        assert param.deserialize(3.14) == 3.14
        assert param.deserialize(2.71) == 2.71


class TestIntParameter:
    """Tests for IntParameter specification."""
    
    def test_construction_with_defaults(self):
        """Test IntParameter with default values."""
        param = IntParameter(name="count", description="Count")
        assert param.name == "count"
        assert param.get_default_value() == 0
        assert param.min_value == -2147483648
        assert param.max_value == 2147483647
        assert param.step_size == 1
    
    def test_construction_with_bounds(self):
        """Test IntParameter with bounds."""
        param = IntParameter(
            name="level",
            description="Level",
            default_value=5,
            min_value=1,
            max_value=10,
            step_size=1
        )
        assert param.get_default_value() == 5
        assert param.min_value == 1
        assert param.max_value == 10
    
    def test_validate(self):
        """Test int parameter validation."""
        param = IntParameter(name="level", description="Level", min_value=1, max_value=10)
        assert param.validate(5) is True
        assert param.validate(1) is True
        assert param.validate(10) is True
        assert param.validate(0) is False
        assert param.validate(11) is False
        assert param.validate(5.5) is False  # floats not allowed
    
    def test_serialization(self):
        """Test int parameter serialization."""
        param = IntParameter(name="count", description="Count", default_value=42)
        assert param.serialize(42) == 42
        assert param.serialize(100) == 100
    
    def test_deserialization(self):
        """Test int parameter deserialization."""
        param = IntParameter(name="count", description="Count")
        assert param.deserialize(42) == 42
        assert param.deserialize(100) == 100


class TestVectorParameter:
    """Tests for VectorParameter specification."""
    
    def test_construction_with_required_fields(self):
        """Test VectorParameter construction with required fields."""
        param = VectorParameter(
            name="position",
            description="Position",
            element_names=["x", "y", "z"],
            default_value=np.array([1.0, 2.0, 3.0])
        )
        assert param.name == "position"
        assert len(param) == 3
        np.testing.assert_array_equal(param.get_default_value(), np.array([1.0, 2.0, 3.0]))
    
    def test_construction_with_mismatched_dimensions(self):
        """Test that mismatched dimensions raise error."""
        with pytest.raises(ValueError, match="doesn't match"):
            VectorParameter(
                name="vec",
                description="Vector",
                element_names=["x", "y", "z"],
                default_value=np.array([1.0, 2.0])  # Wrong size
            )
    
    def test_construction_generates_default_value(self):
        """Test that default value is generated if not provided."""
        param = VectorParameter(
            name="vec",
            description="Vector",
            element_names=["a", "b", "c"]
        )
        np.testing.assert_array_equal(param.get_default_value(), np.zeros(3))
    
    def test_construction_with_bounds(self):
        """Test VectorParameter with bounds."""
        param = VectorParameter(
            name="rgb",
            description="RGB color",
            element_names=["r", "g", "b"],
            default_value=np.array([0.5, 0.5, 0.5]),
            min_value=np.array([0.0, 0.0, 0.0]),
            max_value=np.array([1.0, 1.0, 1.0])
        )
        np.testing.assert_array_equal(param.get_default_value(), np.array([0.5, 0.5, 0.5]))
    
    def test_validate_within_bounds(self):
        """Test validation with bounds."""
        param = VectorParameter(
            name="rgb",
            description="RGB",
            element_names=["r", "g", "b"],
            min_value=np.array([0.0, 0.0, 0.0]),
            max_value=np.array([1.0, 1.0, 1.0])
        )
        assert param.validate(np.array([0.5, 0.5, 0.5])) is True
        assert param.validate(np.array([0.0, 0.0, 0.0])) is True
        assert param.validate(np.array([1.0, 1.0, 1.0])) is True
        assert param.validate(np.array([-0.1, 0.5, 0.5])) is False
        assert param.validate(np.array([0.5, 1.1, 0.5])) is False
    
    def test_serialization(self):
        """Test vector parameter serialization."""
        param = VectorParameter(
            name="pos",
            description="Position",
            element_names=["x", "y", "z"],
            default_value=np.array([1.0, 2.0, 3.0])
        )
        result = param.serialize(np.array([1.0, 2.0, 3.0]))
        assert isinstance(result, list)
        assert result == [1.0, 2.0, 3.0]
    
    def test_deserialization(self):
        """Test vector parameter deserialization."""
        param = VectorParameter(
            name="pos",
            description="Position",
            element_names=["x", "y", "z"]
        )
        result = param.deserialize([1.0, 2.0, 3.0])
        np.testing.assert_array_equal(result, np.array([1.0, 2.0, 3.0]))
    
    def test_len(self):
        """Test vector parameter length."""
        param = VectorParameter(
            name="pos",
            description="Position",
            element_names=["x", "y", "z"]
        )
        assert len(param) == 3
