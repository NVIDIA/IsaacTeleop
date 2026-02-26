# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for DeviceIO source nodes - ControllersSource, HandsSource, HeadSource.

Tests the stateless converters that transform raw DeviceIO flatbuffer data
into standard retargeting engine tensor formats.

NOTE: These tests call source nodes directly with schema objects. In production,
TeleopSession handles this by wrapping schema objects in the appropriate format.
"""

import pytest
import numpy as np
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    HandsSource,
    HeadSource,
)
from isaacteleop.retargeting_engine.interface import TensorGroup
from isaacteleop.retargeting_engine.interface.tensor_group import OptionalTensorGroup
from isaacteleop.retargeting_engine.interface.base_retargeter import _make_output_group
from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex
from isaacteleop.schema import (
    Point,
    Quaternion,
    Pose,
    ControllerPose,
    ControllerInputState,
    ControllerSnapshot,
    Timestamp,
)


# ============================================================================
# Helper Functions to Create FlatBuffer Objects
# ============================================================================


def create_controller_snapshot(grip_pos, aim_pos, trigger_val, is_active=True):
    """Create a ControllerSnapshot using actual FlatBuffer types."""
    # Create grip pose
    grip_position = Point(grip_pos[0], grip_pos[1], grip_pos[2])
    grip_orientation = Quaternion(1.0, 0.0, 0.0, 0.0)  # XYZW format
    grip_pose_obj = Pose(grip_position, grip_orientation)
    grip_controller_pose = ControllerPose(grip_pose_obj, True)

    # Create aim pose
    aim_position = Point(aim_pos[0], aim_pos[1], aim_pos[2])
    aim_orientation = Quaternion(0.707, 0.707, 0.0, 0.0)
    aim_pose_obj = Pose(aim_position, aim_orientation)
    aim_controller_pose = ControllerPose(aim_pose_obj, True)

    # Create input state
    inputs = ControllerInputState(
        primary_click=False,
        secondary_click=False,
        thumbstick_click=False,
        thumbstick_x=0.0,
        thumbstick_y=0.0,
        squeeze_value=0.0,
        trigger_value=trigger_val,
    )

    # Create timestamp
    timestamp = Timestamp(123, 456)

    # Create snapshot
    return ControllerSnapshot(
        grip_controller_pose, aim_controller_pose, inputs, is_active, timestamp
    )


# ============================================================================
# Controllers Source Tests
# ============================================================================


class TestControllersSource:
    """Test ControllersSource functionality."""

    def test_controllers_source_creation(self):
        """Test that ControllersSource can be created."""
        source = ControllersSource(name="controllers")

        assert source.name == "controllers"
        assert source.get_tracker() is not None  # Auto-created tracker

    def test_controllers_source_has_correct_inputs(self):
        """Test that ControllersSource has correct input spec."""
        source = ControllersSource(name="controllers")

        input_spec = source.input_spec()
        assert "deviceio_controller_left" in input_spec
        assert "deviceio_controller_right" in input_spec
        assert len(input_spec) == 2

    def test_controllers_source_outputs(self):
        """Test that ControllersSource has correct outputs."""
        source = ControllersSource(name="controllers")

        output_spec = source.output_spec()
        assert "controller_left" in output_spec
        assert "controller_right" in output_spec
        assert len(output_spec) == 2

    def test_controllers_source_compute(self):
        """Test that ControllersSource converts DeviceIO data correctly.

        Note: This test directly calls compute() which bypasses input validation.
        In production, TeleopSession wraps schema objects appropriately.
        """
        source = ControllersSource(name="controllers")

        # Create raw DeviceIO flatbuffer inputs
        left_snapshot = create_controller_snapshot(
            grip_pos=(0.1, 0.2, 0.3), aim_pos=(0.4, 0.5, 0.6), trigger_val=0.5
        )
        right_snapshot = create_controller_snapshot(
            grip_pos=(0.4, 0.5, 0.6), aim_pos=(0.7, 0.8, 0.9), trigger_val=0.8
        )

        # Call compute directly (bypassing __call__ and its validation)
        # Prepare input dict with schema objects wrapped in lists (simulating TensorGroup access)
        inputs = {
            "deviceio_controller_left": [left_snapshot],
            "deviceio_controller_right": [right_snapshot],
        }

        # Create output structure
        output_spec = source.output_spec()
        outputs = {}
        for name, group_type in output_spec.items():
            outputs[name] = TensorGroup(group_type)

        # Call compute directly
        source.compute(inputs, outputs)

        # Verify left controller data
        left = outputs["controller_left"]
        left_grip_pos = left[ControllerInputIndex.GRIP_POSITION]
        assert isinstance(left_grip_pos, np.ndarray)
        assert left_grip_pos.shape == (3,)
        np.testing.assert_array_almost_equal(left_grip_pos, [0.1, 0.2, 0.3])

        # Verify right controller data
        right = outputs["controller_right"]
        right_grip_pos = right[ControllerInputIndex.GRIP_POSITION]
        assert isinstance(right_grip_pos, np.ndarray)
        assert right_grip_pos.shape == (3,)
        np.testing.assert_array_almost_equal(right_grip_pos, [0.4, 0.5, 0.6])

        # Verify scalar fields (trigger values)
        assert left[ControllerInputIndex.TRIGGER_VALUE] == pytest.approx(0.5)
        assert right[ControllerInputIndex.TRIGGER_VALUE] == pytest.approx(0.8)


# ============================================================================
# Hands Source Tests - Skipped (requires mutable HandPoseT construction)
# ============================================================================


class TestHandsSource:
    """Test HandsSource functionality."""

    def test_hands_source_creation(self):
        """Test that HandsSource can be created."""
        source = HandsSource(name="hands")

        assert source.name == "hands"
        assert source.get_tracker() is not None  # Auto-created tracker

    def test_hands_source_has_correct_inputs(self):
        """Test that HandsSource has correct input spec."""
        source = HandsSource(name="hands")

        input_spec = source.input_spec()
        assert "deviceio_hand_left" in input_spec
        assert "deviceio_hand_right" in input_spec
        assert len(input_spec) == 2

    def test_hands_source_outputs(self):
        """Test that HandsSource has correct outputs."""
        source = HandsSource(name="hands")

        output_spec = source.output_spec()
        assert "hand_left" in output_spec
        assert "hand_right" in output_spec
        assert len(output_spec) == 2


# ============================================================================
# Head Source Tests - Skipped (requires mutable HeadPoseT construction)
# ============================================================================


class TestHeadSource:
    """Test HeadSource functionality."""

    def test_head_source_creation(self):
        """Test that HeadSource can be created."""
        source = HeadSource(name="head")

        assert source.name == "head"
        assert source.get_tracker() is not None  # Auto-created tracker

    def test_head_source_has_correct_inputs(self):
        """Test that HeadSource has correct input spec."""
        source = HeadSource(name="head")

        input_spec = source.input_spec()
        assert "deviceio_head" in input_spec
        assert len(input_spec) == 1

    def test_head_source_outputs(self):
        """Test that HeadSource has correct outputs."""
        source = HeadSource(name="head")

        output_spec = source.output_spec()
        assert "head" in output_spec
        assert len(output_spec) == 1


# ============================================================================
# Optional Behavior Tests
# ============================================================================


class TestControllersSourceOptional:
    """Test that ControllersSource outputs are Optional and handle inactive controllers."""

    def test_output_spec_is_optional(self):
        """Controller outputs must be declared as Optional."""
        source = ControllersSource(name="controllers")
        output_spec = source.output_spec()

        assert output_spec["controller_left"].is_optional
        assert output_spec["controller_right"].is_optional

    def test_active_controller_produces_data(self):
        """Active controllers produce non-absent OptionalTensorGroups."""
        source = ControllersSource(name="controllers")

        left_snapshot = create_controller_snapshot(
            grip_pos=(1, 2, 3), aim_pos=(4, 5, 6), trigger_val=0.5, is_active=True
        )
        right_snapshot = create_controller_snapshot(
            grip_pos=(7, 8, 9), aim_pos=(10, 11, 12), trigger_val=0.9, is_active=True
        )

        inputs = {
            "deviceio_controller_left": [left_snapshot],
            "deviceio_controller_right": [right_snapshot],
        }
        outputs = {
            name: _make_output_group(gt) for name, gt in source.output_spec().items()
        }
        source.compute(inputs, outputs)

        assert not outputs["controller_left"].is_none
        assert not outputs["controller_right"].is_none
        np.testing.assert_array_almost_equal(
            outputs["controller_left"][ControllerInputIndex.GRIP_POSITION], [1, 2, 3]
        )
        assert outputs["controller_right"][
            ControllerInputIndex.TRIGGER_VALUE
        ] == pytest.approx(0.9)

    def test_inactive_controller_sets_none(self):
        """Inactive controllers produce absent OptionalTensorGroups."""
        source = ControllersSource(name="controllers")

        left_snapshot = create_controller_snapshot(
            grip_pos=(0, 0, 0), aim_pos=(0, 0, 0), trigger_val=0.0, is_active=False
        )
        right_snapshot = create_controller_snapshot(
            grip_pos=(0, 0, 0), aim_pos=(0, 0, 0), trigger_val=0.0, is_active=True
        )

        inputs = {
            "deviceio_controller_left": [left_snapshot],
            "deviceio_controller_right": [right_snapshot],
        }
        outputs = {
            name: _make_output_group(gt) for name, gt in source.output_spec().items()
        }
        source.compute(inputs, outputs)

        assert outputs["controller_left"].is_none
        assert not outputs["controller_right"].is_none

    def test_absent_controller_raises_on_access(self):
        """Accessing fields of an absent controller raises ValueError."""
        source = ControllersSource(name="controllers")

        left_snapshot = create_controller_snapshot(
            grip_pos=(0, 0, 0), aim_pos=(0, 0, 0), trigger_val=0.0, is_active=False
        )
        right_snapshot = create_controller_snapshot(
            grip_pos=(0, 0, 0), aim_pos=(0, 0, 0), trigger_val=0.0, is_active=False
        )

        inputs = {
            "deviceio_controller_left": [left_snapshot],
            "deviceio_controller_right": [right_snapshot],
        }
        outputs = {
            name: _make_output_group(gt) for name, gt in source.output_spec().items()
        }
        source.compute(inputs, outputs)

        with pytest.raises(ValueError, match="absent"):
            _ = outputs["controller_left"][ControllerInputIndex.GRIP_POSITION]

        assert outputs["controller_right"].is_none
        outputs["controller_right"][ControllerInputIndex.TRIGGER_VALUE] = 1.0
        assert not outputs["controller_right"].is_none

    def test_output_groups_are_optional_tensor_groups(self):
        """Output groups must be OptionalTensorGroup instances."""
        source = ControllersSource(name="controllers")
        outputs = {
            name: _make_output_group(gt) for name, gt in source.output_spec().items()
        }

        assert isinstance(outputs["controller_left"], OptionalTensorGroup)
        assert isinstance(outputs["controller_right"], OptionalTensorGroup)


class TestHandsSourceOptional:
    """Test that HandsSource outputs are Optional and handle inactive hands."""

    def test_output_spec_is_optional(self):
        """Hand outputs must be declared as Optional."""
        source = HandsSource(name="hands")
        output_spec = source.output_spec()

        assert output_spec["hand_left"].is_optional
        assert output_spec["hand_right"].is_optional

    def test_output_groups_are_optional_tensor_groups(self):
        """Output groups must be OptionalTensorGroup instances."""
        source = HandsSource(name="hands")
        outputs = {
            name: _make_output_group(gt) for name, gt in source.output_spec().items()
        }

        assert isinstance(outputs["hand_left"], OptionalTensorGroup)
        assert isinstance(outputs["hand_right"], OptionalTensorGroup)


class TestHeadSourceNotOptional:
    """Test that HeadSource output is NOT Optional (uses is_valid flag instead)."""

    def test_output_spec_is_not_optional(self):
        """Head output must NOT be Optional."""
        source = HeadSource(name="head")
        output_spec = source.output_spec()

        assert not output_spec["head"].is_optional

    def test_output_group_is_regular_tensor_group(self):
        """Head output must be exactly TensorGroup (required, not optional)."""
        source = HeadSource(name="head")
        outputs = {
            name: _make_output_group(gt) for name, gt in source.output_spec().items()
        }

        assert type(outputs["head"]) is TensorGroup

    def test_set_none_raises_on_head_output(self):
        """Calling set_none on a head output must raise TypeError."""
        source = HeadSource(name="head")
        outputs = {
            name: _make_output_group(gt) for name, gt in source.output_spec().items()
        }

        with pytest.raises(TypeError, match="required"):
            outputs["head"].set_none()
