# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for BaseRetargeter class - testing simple retargeters.

Tests simple retargeting modules including add, double, multiply, and identity operations.
"""

import pytest
from teleopcore.retargeting_engine.interface import (
    BaseRetargeter,
    TensorGroupType,
    TensorGroup,
)
from teleopcore.retargeting_engine.tensor_types import (
    FloatType,
    IntType,
)


# ============================================================================
# Simple Retargeter Implementations for Testing
# ============================================================================


class AddRetargeter(BaseRetargeter):
    """Add two float inputs and output the sum."""
    
    def __init__(self, name: str) -> None:
        super().__init__(name)
    
    def input_spec(self):
        return {
            "a": TensorGroupType("input_a", [FloatType("value")]),
            "b": TensorGroupType("input_b", [FloatType("value")]),
        }
    
    def output_spec(self):
        return {
            "sum": TensorGroupType("output_sum", [FloatType("result")]),
        }
    
    def compute(self, inputs, outputs):
        a = inputs["a"][0]
        b = inputs["b"][0]
        outputs["sum"][0] = a + b


class DoubleRetargeter(BaseRetargeter):
    """Double a float input (multiply by 2)."""
    
    def __init__(self, name: str) -> None:
        super().__init__(name)
    
    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [FloatType("value")]),
        }
    
    def output_spec(self):
        return {
            "result": TensorGroupType("output_result", [FloatType("doubled")]),
        }
    
    def compute(self, inputs, outputs):
        x = inputs["x"][0]
        outputs["result"][0] = x * 2.0


class MultiplyRetargeter(BaseRetargeter):
    """Multiply two float inputs."""
    
    def __init__(self, name: str) -> None:
        super().__init__(name)
    
    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [FloatType("value")]),
            "y": TensorGroupType("input_y", [FloatType("value")]),
        }
    
    def output_spec(self):
        return {
            "product": TensorGroupType("output_product", [FloatType("result")]),
        }
    
    def compute(self, inputs, outputs):
        x = inputs["x"][0]
        y = inputs["y"][0]
        outputs["product"][0] = x * y


class IdentityRetargeter(BaseRetargeter):
    """Pass through input unchanged."""
    
    def __init__(self, name: str) -> None:
        super().__init__(name)
    
    def input_spec(self):
        return {
            "value": TensorGroupType("input_value", [FloatType("x")]),
        }
    
    def output_spec(self):
        return {
            "value": TensorGroupType("output_value", [FloatType("x")]),
        }
    
    def compute(self, inputs, outputs):
        outputs["value"][0] = inputs["value"][0]


class MultiOutputRetargeter(BaseRetargeter):
    """Retargeter with multiple outputs."""
    
    def __init__(self, name: str) -> None:
        super().__init__(name)
    
    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [FloatType("value")]),
        }
    
    def output_spec(self):
        return {
            "doubled": TensorGroupType("output_doubled", [FloatType("x2")]),
            "tripled": TensorGroupType("output_tripled", [FloatType("x3")]),
            "squared": TensorGroupType("output_squared", [FloatType("x_sq")]),
        }
    
    def compute(self, inputs, outputs):
        x = inputs["x"][0]
        outputs["doubled"][0] = x * 2.0
        outputs["tripled"][0] = x * 3.0
        outputs["squared"][0] = x * x


class IntAddRetargeter(BaseRetargeter):
    """Add two integer inputs."""
    
    def __init__(self, name: str) -> None:
        super().__init__(name)
    
    def input_spec(self):
        return {
            "a": TensorGroupType("input_a", [IntType("value")]),
            "b": TensorGroupType("input_b", [IntType("value")]),
        }
    
    def output_spec(self):
        return {
            "sum": TensorGroupType("output_sum", [IntType("result")]),
        }
    
    def compute(self, inputs, outputs):
        a = inputs["a"][0]
        b = inputs["b"][0]
        outputs["sum"][0] = a + b


# ============================================================================
# Test Classes
# ============================================================================


class TestRetargeterConstruction:
    """Test retargeter construction and initialization."""
    
    def test_add_retargeter_construction(self):
        """Test constructing an AddRetargeter."""
        retargeter = AddRetargeter("add")
        
        assert retargeter._name == "add"
        assert "a" in retargeter._inputs
        assert "b" in retargeter._inputs
        assert "sum" in retargeter._outputs
    
    def test_double_retargeter_construction(self):
        """Test constructing a DoubleRetargeter."""
        retargeter = DoubleRetargeter("double")
        
        assert retargeter._name == "double"
        assert "x" in retargeter._inputs
        assert "result" in retargeter._outputs
    
    def test_custom_name(self):
        """Test constructing retargeter with custom name."""
        retargeter = AddRetargeter(name="custom_add")
        
        assert retargeter._name == "custom_add"


class TestBasicRetargeterExecution:
    """Test executing basic retargeters."""
    
    def test_add_retargeter_basic(self):
        """Test AddRetargeter with simple values."""
        retargeter = AddRetargeter("add_test")
        
        # Create inputs
        input_a = TensorGroup(TensorGroupType("a", [FloatType("value")]))
        input_b = TensorGroup(TensorGroupType("b", [FloatType("value")]))
        input_a[0] = 3.0
        input_b[0] = 4.0
        
        # Execute
        outputs = retargeter({"a": input_a, "b": input_b})
        
        # Check output
        assert "sum" in outputs
        assert outputs["sum"][0] == 7.0
    
    def test_double_retargeter_basic(self):
        """Test DoubleRetargeter with simple value."""
        retargeter = DoubleRetargeter("double_test")
        
        # Create input
        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 5.0
        
        # Execute
        outputs = retargeter({"x": input_x})
        
        # Check output
        assert "result" in outputs
        assert outputs["result"][0] == 10.0
    
    def test_multiply_retargeter_basic(self):
        """Test MultiplyRetargeter."""
        retargeter = MultiplyRetargeter("multiply_test")
        
        # Create inputs
        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_y = TensorGroup(TensorGroupType("y", [FloatType("value")]))
        input_x[0] = 3.0
        input_y[0] = 7.0
        
        # Execute
        outputs = retargeter({"x": input_x, "y": input_y})
        
        # Check output
        assert "product" in outputs
        assert outputs["product"][0] == 21.0
    
    def test_identity_retargeter_basic(self):
        """Test IdentityRetargeter."""
        retargeter = IdentityRetargeter("identity_test")
        
        # Create input
        input_value = TensorGroup(TensorGroupType("value", [FloatType("x")]))
        input_value[0] = 42.5
        
        # Execute
        outputs = retargeter({"value": input_value})
        
        # Check output
        assert "value" in outputs
        assert outputs["value"][0] == 42.5
    
    def test_int_add_retargeter_basic(self):
        """Test IntAddRetargeter with integers."""
        retargeter = IntAddRetargeter("int_add_test")
        
        # Create inputs
        input_a = TensorGroup(TensorGroupType("a", [IntType("value")]))
        input_b = TensorGroup(TensorGroupType("b", [IntType("value")]))
        input_a[0] = 10
        input_b[0] = 25
        
        # Execute
        outputs = retargeter({"a": input_a, "b": input_b})
        
        # Check output
        assert "sum" in outputs
        assert outputs["sum"][0] == 35


class TestMultiOutputRetargeter:
    """Test retargeter with multiple outputs."""
    
    def test_multi_output_basic(self):
        """Test MultiOutputRetargeter."""
        retargeter = MultiOutputRetargeter("multi_test")
        
        # Create input
        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 5.0
        
        # Execute
        outputs = retargeter({"x": input_x})
        
        # Check all outputs
        assert "doubled" in outputs
        assert "tripled" in outputs
        assert "squared" in outputs
        assert outputs["doubled"][0] == 10.0
        assert outputs["tripled"][0] == 15.0
        assert outputs["squared"][0] == 25.0
    
    def test_multi_output_with_zero(self):
        """Test MultiOutputRetargeter with zero input."""
        retargeter = MultiOutputRetargeter("multi_zero_test")
        
        # Create input
        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 0.0
        
        # Execute
        outputs = retargeter({"x": input_x})
        
        # Check all outputs
        assert outputs["doubled"][0] == 0.0
        assert outputs["tripled"][0] == 0.0
        assert outputs["squared"][0] == 0.0
    
    def test_multi_output_with_negative(self):
        """Test MultiOutputRetargeter with negative input."""
        retargeter = MultiOutputRetargeter("multi_neg_test")
        
        # Create input
        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = -3.0
        
        # Execute
        outputs = retargeter({"x": input_x})
        
        # Check all outputs
        assert outputs["doubled"][0] == -6.0
        assert outputs["tripled"][0] == -9.0
        assert outputs["squared"][0] == 9.0


class TestRetargeterInputValidation:
    """Test input validation for retargeters."""
    
    def test_missing_input_raises(self):
        """Test that missing input raises error."""
        retargeter = AddRetargeter("add_missing_test")
        
        # Create only one input (missing "b")
        input_a = TensorGroup(TensorGroupType("a", [FloatType("value")]))
        input_a[0] = 3.0
        
        # Should raise due to missing input
        with pytest.raises(ValueError, match="Expected inputs"):
            retargeter({"a": input_a})
    
    def test_extra_input_raises(self):
        """Test that extra input raises error."""
        retargeter = DoubleRetargeter("double_extra_test")
        
        # Create correct input plus extra
        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_y = TensorGroup(TensorGroupType("y", [FloatType("value")]))
        input_x[0] = 5.0
        input_y[0] = 10.0
        
        # Should raise due to extra input
        with pytest.raises(ValueError, match="Expected inputs"):
            retargeter({"x": input_x, "y": input_y})
    
    def test_wrong_input_type_raises(self):
        """Test that wrong input type raises error."""
        retargeter = AddRetargeter("add_type_test")  # Expects float inputs
        
        # Create int inputs instead
        input_a = TensorGroup(TensorGroupType("a", [IntType("value")]))
        input_b = TensorGroup(TensorGroupType("b", [IntType("value")]))
        input_a[0] = 3
        input_b[0] = 4
        
        # Should raise due to type mismatch
        with pytest.raises(ValueError):
            retargeter({"a": input_a, "b": input_b})


class TestRetargeterEdgeCases:
    """Test edge cases and special values."""
    
    def test_add_with_negative_numbers(self):
        """Test AddRetargeter with negative numbers."""
        retargeter = AddRetargeter("add_negative_test")
        
        input_a = TensorGroup(TensorGroupType("a", [FloatType("value")]))
        input_b = TensorGroup(TensorGroupType("b", [FloatType("value")]))
        input_a[0] = -5.0
        input_b[0] = 3.0
        
        outputs = retargeter({"a": input_a, "b": input_b})
        
        assert outputs["sum"][0] == -2.0
    
    def test_add_with_zero(self):
        """Test AddRetargeter with zero."""
        retargeter = AddRetargeter("add_zero_test")
        
        input_a = TensorGroup(TensorGroupType("a", [FloatType("value")]))
        input_b = TensorGroup(TensorGroupType("b", [FloatType("value")]))
        input_a[0] = 0.0
        input_b[0] = 7.0
        
        outputs = retargeter({"a": input_a, "b": input_b})
        
        assert outputs["sum"][0] == 7.0
    
    def test_double_with_large_number(self):
        """Test DoubleRetargeter with large number."""
        retargeter = DoubleRetargeter("double_large_test")
        
        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 1e6
        
        outputs = retargeter({"x": input_x})
        
        assert outputs["result"][0] == 2e6
    
    def test_multiply_with_zero(self):
        """Test MultiplyRetargeter with zero."""
        retargeter = MultiplyRetargeter("multiply_zero_test")
        
        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_y = TensorGroup(TensorGroupType("y", [FloatType("value")]))
        input_x[0] = 5.0
        input_y[0] = 0.0
        
        outputs = retargeter({"x": input_x, "y": input_y})
        
        assert outputs["product"][0] == 0.0


class TestRetargeterReuse:
    """Test that retargeters can be reused with different inputs."""
    
    def test_add_retargeter_reuse(self):
        """Test reusing AddRetargeter with different inputs."""
        retargeter = AddRetargeter("add_reuse_test")
        
        # First execution
        input_a = TensorGroup(TensorGroupType("a", [FloatType("value")]))
        input_b = TensorGroup(TensorGroupType("b", [FloatType("value")]))
        input_a[0] = 1.0
        input_b[0] = 2.0
        
        outputs1 = retargeter({"a": input_a, "b": input_b})
        assert outputs1["sum"][0] == 3.0
        
        # Second execution with new inputs
        input_a[0] = 10.0
        input_b[0] = 20.0
        
        outputs2 = retargeter({"a": input_a, "b": input_b})
        assert outputs2["sum"][0] == 30.0
        
        # Verify first outputs weren't modified
        assert outputs1["sum"][0] == 3.0
    
    def test_double_retargeter_reuse(self):
        """Test reusing DoubleRetargeter."""
        retargeter = DoubleRetargeter("double_reuse_test")
        
        # Multiple executions
        for value in [1.0, 5.0, 10.0, -3.0]:
            input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
            input_x[0] = value
            
            outputs = retargeter({"x": input_x})
            assert outputs["result"][0] == value * 2.0


class TestRetargeterOutputSelector:
    """Test output selector for connecting retargeters."""
    
    def test_output_selector_creation(self):
        """Test creating output selector."""
        retargeter = AddRetargeter("add_selector_test")
        
        output_sel = retargeter.output("sum")
        
        assert output_sel.module == retargeter
        assert output_sel.output_name == "sum"
    
    def test_output_selector_repr(self):
        """Test output selector string representation."""
        retargeter = AddRetargeter("add_repr_test")
        
        output_sel = retargeter.output("sum")
        repr_str = repr(output_sel)
        
        # Just check that repr returns something containing OutputSelector
        assert "OutputSelector" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

