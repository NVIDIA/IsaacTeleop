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

def create_controller_snapshot(grip_pos, aim_pos, trigger_val):
    """Create a ControllerSnapshot using actual FlatBuffer types."""
    # Create grip pose
    grip_position = Point(grip_pos[0], grip_pos[1], grip_pos[2])
    grip_orientation = Quaternion(1.0, 0.0, 0.0, 0.0)  # XYZW format
    grip_pose_obj = Pose(grip_position, grip_orientation)
    grip_controller_pose = ControllerPose(True, grip_pose_obj)
    
    # Create aim pose  
    aim_position = Point(aim_pos[0], aim_pos[1], aim_pos[2])
    aim_orientation = Quaternion(0.707, 0.707, 0.0, 0.0)
    aim_pose_obj = Pose(aim_position, aim_orientation)
    aim_controller_pose = ControllerPose(True, aim_pose_obj)
    
    # Create input state
    inputs = ControllerInputState(
        primary_click=False,
        secondary_click=False,
        thumbstick_click=False,
        thumbstick_x=0.0,
        thumbstick_y=0.0,
        squeeze_value=0.0,
        trigger_value=trigger_val
    )
    
    # Create timestamp
    timestamp = Timestamp(123, 456)
    
    # Create snapshot
    return ControllerSnapshot(True, grip_controller_pose, aim_controller_pose, inputs, timestamp)


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
            grip_pos=(0.1, 0.2, 0.3),
            aim_pos=(0.4, 0.5, 0.6),
            trigger_val=0.5
        )
        right_snapshot = create_controller_snapshot(
            grip_pos=(0.4, 0.5, 0.6),
            aim_pos=(0.7, 0.8, 0.9),
            trigger_val=0.8
        )
        
        # Call compute directly (bypassing __call__ and its validation)
        # Prepare input dict with schema objects wrapped in lists (simulating TensorGroup access)
        inputs = {
            "deviceio_controller_left": [left_snapshot],
            "deviceio_controller_right": [right_snapshot]
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
        left_grip_pos = left[0]  # grip_position
        assert isinstance(left_grip_pos, np.ndarray)
        assert left_grip_pos.shape == (3,)
        np.testing.assert_array_almost_equal(left_grip_pos, [0.1, 0.2, 0.3])
        
        # Verify right controller data
        right = outputs["controller_right"]
        right_grip_pos = right[0]  # grip_position
        assert isinstance(right_grip_pos, np.ndarray)
        assert right_grip_pos.shape == (3,)
        np.testing.assert_array_almost_equal(right_grip_pos, [0.4, 0.5, 0.6])
        
        # Verify scalar fields (trigger values)
        assert left[10] == pytest.approx(0.5)  # trigger_value for left
        assert right[10] == pytest.approx(0.8)  # trigger_value for right
        
        # Verify is_active
        assert left[11] == True
        assert right[11] == True


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
