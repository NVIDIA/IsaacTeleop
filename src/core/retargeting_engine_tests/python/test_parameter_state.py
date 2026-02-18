# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for ParameterState."""

import pytest
import tempfile
import os
import numpy as np
from isaacteleop.retargeting_engine.interface.parameter_state import ParameterState
from isaacteleop.retargeting_engine.interface.tunable_parameter import (
    BoolParameter,
    FloatParameter,
    IntParameter,
    VectorParameter,
)


class TestParameterState:
    """Tests for ParameterState."""

    def test_construction_empty_raises_error(self):
        """Test ParameterState with no parameters raises ValueError."""
        with pytest.raises(ValueError, match="at least one parameter"):
            ParameterState(name="empty", parameters=[])

    def test_register_parameter(self):
        """Test registering parameters via constructor."""
        bool_param = BoolParameter(name="enabled", description="Enable")
        float_param = FloatParameter(
            name="alpha", description="Alpha", min_value=0.0, max_value=1.0
        )

        state = ParameterState(name="test", parameters=[bool_param, float_param])

        params = state.get_all_parameter_specs()
        assert "enabled" in params
        assert "alpha" in params
        assert params["enabled"] == bool_param
        assert params["alpha"] == float_param

    def test_get_parameter_value(self):
        """Test getting parameter values."""
        param = FloatParameter(name="value", description="Value", default_value=3.14)
        state = ParameterState(name="test", parameters=[param])

        values = state.get_all_values()
        assert values["value"] == 3.14

    def test_set_parameter_value(self):
        """Test setting parameter values."""
        param = FloatParameter(name="value", description="Value", default_value=1.0)
        state = ParameterState(name="test", parameters=[param])

        state.set({"value": 5.0})
        values = state.get_all_values()
        assert values["value"] == 5.0

    def test_get_nonexistent_parameter(self):
        """Test getting nonexistent parameter via get_all_values is safe."""
        param = FloatParameter(name="value", description="Value", default_value=1.0)
        state = ParameterState(name="test", parameters=[param])
        values = state.get_all_values()
        assert "nonexistent" not in values

    def test_set_nonexistent_parameter_raises_error(self):
        """Test setting nonexistent parameter raises error."""
        param = FloatParameter(name="value", description="Value", default_value=1.0)
        state = ParameterState(name="test", parameters=[param])
        with pytest.raises(KeyError):
            state.set({"nonexistent": 42})

    def test_reset_to_defaults(self):
        """Test resetting all parameters to defaults."""
        float_param = FloatParameter(
            name="alpha", description="Alpha", default_value=0.5
        )
        int_param = IntParameter(name="count", description="Count", default_value=10)

        state = ParameterState(name="test", parameters=[float_param, int_param])

        # Change values
        state.set({"alpha": 0.9, "count": 50})
        values = state.get_all_values()
        assert values["alpha"] == 0.9
        assert values["count"] == 50

        # Reset to defaults
        state.reset_to_defaults()
        values = state.get_all_values()
        assert values["alpha"] == 0.5
        assert values["count"] == 10

    def test_save_and_load_to_file(self):
        """Test saving and loading parameter state to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")

            # Create state with parameters
            parameters = [
                BoolParameter(
                    name="enabled", description="Enable", default_value=False
                ),
                FloatParameter(name="alpha", description="Alpha", default_value=0.5),
                IntParameter(name="count", description="Count", default_value=10),
                VectorParameter(
                    name="position",
                    description="Position",
                    element_names=["x", "y", "z"],
                    default_value=np.array([1.0, 2.0, 3.0]),
                ),
            ]
            state = ParameterState(
                name="test", parameters=parameters, config_file=config_path
            )

            # Modify values
            state.set(
                {
                    "enabled": True,
                    "alpha": 0.8,
                    "count": 25,
                    "position": [4.0, 5.0, 6.0],
                }
            )

            # Save to file
            assert state.save_to_file() is True
            assert os.path.exists(config_path)

            # Create new state and load
            parameters2 = [
                BoolParameter(
                    name="enabled", description="Enable", default_value=False
                ),
                FloatParameter(name="alpha", description="Alpha", default_value=0.5),
                IntParameter(name="count", description="Count", default_value=10),
                VectorParameter(
                    name="position",
                    description="Position",
                    element_names=["x", "y", "z"],
                    default_value=np.array([1.0, 2.0, 3.0]),
                ),
            ]
            state2 = ParameterState(
                name="test", parameters=parameters2, config_file=config_path
            )

            # Verify loaded values
            values = state2.get_all_values()
            assert values["enabled"] is True
            assert values["alpha"] == 0.8
            assert values["count"] == 25
            np.testing.assert_array_almost_equal(
                values["position"], np.array([4.0, 5.0, 6.0])
            )

    def test_load_nonexistent_file_doesnt_error(self):
        """Test loading from nonexistent file doesn't error."""
        param = FloatParameter(name="value", description="Value", default_value=1.0)
        try:
            ParameterState(
                name="test", parameters=[param], config_file="/nonexistent/path.json"
            )
        except Exception as e:
            # Should not raise error during construction
            assert False, f"Unexpected exception raised: {e}"

    def test_load_from_file_after_save(self):
        """Test loading from saved file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")

            param = FloatParameter(name="alpha", description="Alpha", default_value=0.5)
            state = ParameterState(
                name="test", parameters=[param], config_file=config_path
            )

            # Set and save
            state.set({"alpha": 0.8})
            state.save_to_file()

            # Change again
            state.set({"alpha": 0.9})
            values = state.get_all_values()
            assert values["alpha"] == 0.9

            # Load from saved file
            assert state.load_from_file() is True
            values = state.get_all_values()
            assert values["alpha"] == 0.8

    def test_load_from_file_without_file_returns_false(self):
        """Test load_from_file returns False when no saved file exists."""
        param = FloatParameter(name="alpha", description="Alpha", default_value=0.5)
        state = ParameterState(name="test", parameters=[param])
        assert state.load_from_file() is False

    def test_thread_safety_basic(self):
        """Test basic thread safety of get/set operations."""
        import threading

        param = IntParameter(name="counter", description="Counter", default_value=0)
        state = ParameterState(name="test", parameters=[param])

        def increment():
            for _ in range(100):
                values = state.get_all_values()
                state.set({"counter": values["counter"] + 1})

        threads = [threading.Thread(target=increment) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Due to the lock, we should get exactly 500
        values = state.get_all_values()
        assert values["counter"] == 500

    def test_multiple_parameters_of_different_types(self):
        """Test state with multiple parameter types."""
        parameters = [
            BoolParameter(name="flag", description="Flag", default_value=True),
            FloatParameter(name="scale", description="Scale", default_value=1.0),
            IntParameter(name="level", description="Level", default_value=5),
            VectorParameter(
                name="color",
                description="Color",
                element_names=["r", "g", "b"],
                default_value=np.array([1.0, 0.0, 0.0]),
            ),
        ]
        state = ParameterState(name="test", parameters=parameters)

        # Verify all parameters exist
        params = state.get_all_parameter_specs()
        assert len(params) == 4
        assert "flag" in params
        assert "scale" in params
        assert "level" in params
        assert "color" in params

        # Verify default values
        values = state.get_all_values()
        assert values["flag"] is True
        assert values["scale"] == 1.0
        assert values["level"] == 5
        np.testing.assert_array_equal(values["color"], np.array([1.0, 0.0, 0.0]))

    # def test_config_path_property(self):
    #     """Test config file path."""
    #     param = FloatParameter(name="value", description="Value", default_value=1.0)
    #     state = ParameterState(
    #         name="test", parameters=[param], config_file="/path/to/config.json"
    #     )
    #     # ParameterState doesn't expose config_path as a property in the actual implementation
    #     # This test would need to be removed or modified
    #     pass

    def test_batch_get_specific_parameters(self):
        """Test getting specific parameters with the batch get API."""
        parameters = [
            BoolParameter(name="enabled", description="Enable", default_value=False),
            FloatParameter(name="alpha", description="Alpha", default_value=0.5),
            IntParameter(name="count", description="Count", default_value=10),
        ]
        state = ParameterState(name="test", parameters=parameters)

        # Get only specific parameters
        values = state.get(["enabled", "count"])
        assert len(values) == 2
        assert "enabled" in values
        assert "count" in values
        assert "alpha" not in values
        assert values["enabled"] is False
        assert values["count"] == 10

    def test_batch_get_nonexistent_parameter_raises_error(self):
        """Test that batch get raises error for nonexistent parameter."""
        param = FloatParameter(name="alpha", description="Alpha", default_value=0.5)
        state = ParameterState(name="test", parameters=[param])

        with pytest.raises(KeyError):
            state.get(["alpha", "nonexistent"])

    def test_batch_set_multiple_parameters(self):
        """Test setting multiple parameters atomically."""
        parameters = [
            BoolParameter(name="enabled", description="Enable", default_value=False),
            FloatParameter(name="alpha", description="Alpha", default_value=0.5),
            IntParameter(name="count", description="Count", default_value=10),
        ]
        state = ParameterState(name="test", parameters=parameters)

        # Set multiple parameters at once
        state.set({"enabled": True, "alpha": 0.8, "count": 25})

        values = state.get_all_values()
        assert values["enabled"] is True
        assert values["alpha"] == 0.8
        assert values["count"] == 25

    def test_batch_set_partial_update(self):
        """Test that batch set can update a subset of parameters."""
        parameters = [
            BoolParameter(name="enabled", description="Enable", default_value=False),
            FloatParameter(name="alpha", description="Alpha", default_value=0.5),
            IntParameter(name="count", description="Count", default_value=10),
        ]
        state = ParameterState(name="test", parameters=parameters)

        # Set only some parameters
        state.set({"alpha": 0.9})

        values = state.get_all_values()
        assert values["enabled"] is False  # Unchanged
        assert values["alpha"] == 0.9  # Updated
        assert values["count"] == 10  # Unchanged
