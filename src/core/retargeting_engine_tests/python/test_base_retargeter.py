# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for BaseRetargeter class - testing simple retargeters.

Tests simple retargeting modules including add, double, multiply, and identity operations.
Also tests parameter functionality in retargeters.
"""

import pytest
import tempfile
import os
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    TensorGroupType,
    TensorGroup,
    ParameterState,
)
from isaacteleop.retargeting_engine.interface.tunable_parameter import (
    FloatParameter,
    IntParameter,
    BoolParameter,
)
from isaacteleop.retargeting_engine.tensor_types import (
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
        with pytest.raises(ValueError, match="Required input"):
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
        with pytest.raises(ValueError, match="Unexpected inputs"):
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


# ============================================================================
# Parametric Retargeters for Testing Parameters
# ============================================================================


class ParametricScaleRetargeter(BaseRetargeter):
    """Retargeter with a tunable scale parameter."""

    def __init__(self, name: str, config_file: str = None) -> None:
        # Create parameter with sync function
        parameters = [
            FloatParameter(
                "scale",
                "Scale factor",
                default_value=1.0,
                min_value=0.0,
                max_value=10.0,
                sync_fn=lambda v: setattr(self, "scale", v),
            )
        ]
        param_state = ParameterState(
            name, parameters=parameters, config_file=config_file
        )

        super().__init__(name, parameter_state=param_state)
        # self.scale is now initialized via sync_fn

    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [FloatType("value")]),
        }

    def output_spec(self):
        return {
            "result": TensorGroupType("output_result", [FloatType("scaled")]),
        }

    def compute(self, inputs, outputs):
        outputs["result"][0] = inputs["x"][0] * self.scale


class ParametricOffsetRetargeter(BaseRetargeter):
    """Retargeter with tunable offset and enable parameters."""

    def __init__(self, name: str) -> None:
        parameters = [
            FloatParameter(
                "offset",
                "Offset value",
                default_value=0.0,
                sync_fn=lambda v: setattr(self, "offset", v),
            ),
            BoolParameter(
                "enabled",
                "Enable offset",
                default_value=True,
                sync_fn=lambda v: setattr(self, "enabled", v),
            ),
        ]
        param_state = ParameterState(name, parameters=parameters)

        super().__init__(name, parameter_state=param_state)

    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [FloatType("value")]),
        }

    def output_spec(self):
        return {
            "result": TensorGroupType("output_result", [FloatType("value")]),
        }

    def compute(self, inputs, outputs):
        value = inputs["x"][0]
        if self.enabled:
            outputs["result"][0] = value + self.offset
        else:
            outputs["result"][0] = value


class ParametricIntMultiplierRetargeter(BaseRetargeter):
    """Retargeter with an integer multiplier parameter."""

    def __init__(self, name: str) -> None:
        parameters = [
            IntParameter(
                "multiplier",
                "Integer multiplier",
                default_value=2,
                min_value=1,
                max_value=100,
                sync_fn=lambda v: setattr(self, "multiplier", v),
            )
        ]
        param_state = ParameterState(name, parameters=parameters)

        super().__init__(name, parameter_state=param_state)

    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [IntType("value")]),
        }

    def output_spec(self):
        return {
            "result": TensorGroupType("output_result", [IntType("value")]),
        }

    def compute(self, inputs, outputs):
        outputs["result"][0] = inputs["x"][0] * self.multiplier


# ============================================================================
# Parameter Tests
# ============================================================================


class TestRetargeterWithParameters:
    """Test retargeters with tunable parameters."""

    def test_parametric_retargeter_construction(self):
        """Test constructing a parametric retargeter."""
        retargeter = ParametricScaleRetargeter("scale_test")

        assert retargeter._name == "scale_test"
        assert retargeter._parameter_state is not None
        assert hasattr(retargeter, "scale")
        assert retargeter.scale == 1.0  # Default value

    def test_parametric_retargeter_get_parameter_state(self):
        """Test getting parameter state from retargeter."""
        retargeter = ParametricScaleRetargeter("scale_test")

        param_state = retargeter.get_parameter_state()
        assert param_state is not None
        assert "scale" in param_state.get_all_parameter_specs()

    def test_parametric_retargeter_basic_execution(self):
        """Test executing parametric retargeter with default parameters."""
        retargeter = ParametricScaleRetargeter("scale_basic")

        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 5.0

        outputs = retargeter({"x": input_x})

        # With default scale=1.0
        assert outputs["result"][0] == 5.0

    def test_parametric_retargeter_with_changed_parameter(self):
        """Test executing with changed parameter value."""
        retargeter = ParametricScaleRetargeter("scale_changed")

        # Change parameter
        param_state = retargeter.get_parameter_state()
        param_state.set({"scale": 2.5})

        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 4.0

        outputs = retargeter({"x": input_x})

        # With scale=2.5
        assert outputs["result"][0] == 10.0

    def test_parametric_retargeter_parameter_sync(self):
        """Test that parameters are synced before compute."""
        retargeter = ParametricScaleRetargeter("scale_sync")

        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 3.0

        # First execution with default
        outputs1 = retargeter({"x": input_x})
        assert outputs1["result"][0] == 3.0  # scale=1.0

        # Change parameter
        param_state = retargeter.get_parameter_state()
        param_state.set({"scale": 3.0})

        # Second execution - parameter should be synced
        outputs2 = retargeter({"x": input_x})
        assert outputs2["result"][0] == 9.0  # scale=3.0

    def test_parametric_offset_retargeter_with_bool_parameter(self):
        """Test retargeter with bool and float parameters."""
        retargeter = ParametricOffsetRetargeter("offset_test")

        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 10.0

        param_state = retargeter.get_parameter_state()
        param_state.set({"offset": 5.0, "enabled": True})

        # With offset enabled
        outputs1 = retargeter({"x": input_x})
        assert outputs1["result"][0] == 15.0

        # Disable offset
        param_state.set({"enabled": False})
        outputs2 = retargeter({"x": input_x})
        assert outputs2["result"][0] == 10.0  # No offset applied

    def test_parametric_int_multiplier(self):
        """Test retargeter with integer parameter."""
        retargeter = ParametricIntMultiplierRetargeter("int_mult_test")

        input_x = TensorGroup(TensorGroupType("x", [IntType("value")]))
        input_x[0] = 7

        # Default multiplier=2
        outputs1 = retargeter({"x": input_x})
        assert outputs1["result"][0] == 14

        # Change multiplier
        param_state = retargeter.get_parameter_state()
        param_state.set({"multiplier": 5})

        outputs2 = retargeter({"x": input_x})
        assert outputs2["result"][0] == 35

    def test_parametric_retargeter_save_and_load(self):
        """Test saving and loading parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")

            # Create retargeter and set parameter
            retargeter1 = ParametricScaleRetargeter(
                "scale_save", config_file=config_path
            )
            param_state1 = retargeter1.get_parameter_state()
            param_state1.set({"scale": 3.5})
            param_state1.save_to_file()

            # Create new retargeter with same config file
            retargeter2 = ParametricScaleRetargeter(
                "scale_load", config_file=config_path
            )

            # Should load saved value
            assert retargeter2.scale == 3.5

            # Test execution with loaded value
            input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
            input_x[0] = 2.0
            outputs = retargeter2({"x": input_x})
            assert outputs["result"][0] == 7.0  # 2.0 * 3.5

    def test_parametric_retargeter_reset_to_defaults(self):
        """Test resetting parameters to defaults."""
        retargeter = ParametricScaleRetargeter("scale_reset")
        param_state = retargeter.get_parameter_state()

        # Change parameter and execute to sync
        param_state.set({"scale": 5.0})

        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 2.0

        # Execute to trigger sync
        outputs1 = retargeter({"x": input_x})
        assert outputs1["result"][0] == 10.0  # 2.0 * 5.0
        assert retargeter.scale == 5.0

        # Reset to defaults and execute again
        param_state.reset_to_defaults()
        outputs2 = retargeter({"x": input_x})

        assert retargeter.scale == 1.0  # Default value
        assert outputs2["result"][0] == 2.0  # 2.0 * 1.0

    def test_retargeter_without_parameters(self):
        """Test that retargeter without parameters works normally."""
        retargeter = AddRetargeter("add_no_params")

        # Should not have parameter state
        assert retargeter.get_parameter_state() is None

        # Should execute normally
        input_a = TensorGroup(TensorGroupType("a", [FloatType("value")]))
        input_b = TensorGroup(TensorGroupType("b", [FloatType("value")]))
        input_a[0] = 3.0
        input_b[0] = 4.0

        outputs = retargeter({"a": input_a, "b": input_b})
        assert outputs["sum"][0] == 7.0

    def test_parametric_retargeter_multiple_executions(self):
        """Test multiple executions with parameter changes."""
        retargeter = ParametricScaleRetargeter("scale_multi")
        param_state = retargeter.get_parameter_state()

        input_x = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        input_x[0] = 10.0

        # Execute with different scale values
        test_cases = [
            (1.0, 10.0),
            (2.0, 20.0),
            (0.5, 5.0),
            (3.5, 35.0),
        ]

        for scale, expected in test_cases:
            param_state.set({"scale": scale})
            outputs = retargeter({"x": input_x})
            assert outputs["result"][0] == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
