# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for source modules - ControllersSource, HandsSource, HeadSource.

Tests the DeviceIO tracker wrapper sources that provide data to retargeting graphs.

These tests use actual FlatBuffer schema types from teleopcore.schema to construct
mock tracker return values, matching how DeviceIO returns data from C++.
"""

import pytest
import numpy as np
from teleopcore.retargeting_engine.sources import (
    ControllersSource,
    HandsSource,
    HeadSource,
)
from teleopcore.retargeting_engine.tensor_types import NUM_HAND_JOINTS
from teleopcore.schema import (
    Point,
    Quaternion,
    Pose,
    HandJointPose,
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
        trigger_value=trigger_val
    )
    
    # Create timestamp
    timestamp = Timestamp(123, 456)
    
    # Create snapshot
    return ControllerSnapshot(grip_controller_pose, aim_controller_pose, inputs, True, timestamp)


def create_hand_joints():
    """Create HandJoints array using actual FlatBuffer types."""
    # HandJoints is a fixed-size array struct, but from the bindings it's read-only
    # We need to create individual HandJointPose objects
    joints = []
    for i in range(NUM_HAND_JOINTS):
        position = Point(i * 0.1, i * 0.2, i * 0.3)
        orientation = Quaternion(1.0, 0.0, 0.0, 0.0)
        pose = Pose(position, orientation)
        joint = HandJointPose(pose, True, 0.01)
        joints.append(joint)
    return joints


# ============================================================================
# Mock Tracker Classes Using FlatBuffer Types
# ============================================================================

class MockSession:
    """Mock DeviceIOSession for testing."""
    pass


class MockControllerData:
    """Mock ControllerDataT with left and right controllers."""
    def __init__(self):
        self.left_controller = create_controller_snapshot(
            grip_pos=(0.1, 0.2, 0.3),
            aim_pos=(0.4, 0.5, 0.6),
            trigger_val=0.5
        )
        self.right_controller = create_controller_snapshot(
            grip_pos=(0.4, 0.5, 0.6),
            aim_pos=(0.7, 0.8, 0.9),
            trigger_val=0.8
        )


class MockControllerTracker:
    """Mock ControllerTracker that returns actual FlatBuffer types."""
    def get_controller_data(self, session):
        """Return mock controller data using FlatBuffer types."""
        return MockControllerData()


class MockHandJoints:
    """Mock HandJoints struct that wraps FlatBuffer HandJointPose objects."""
    def __init__(self):
        self._joints = create_hand_joints()
    
    def __getitem__(self, index):
        return self._joints[index]
    
    def __len__(self):
        return len(self._joints)


class MockHandData:
    """Mock HandPoseT using FlatBuffer types for joints."""
    def __init__(self):
        self.joints = MockHandJoints()
        self.is_active = True
        self.timestamp = Timestamp(123456789, 987654321)


class MockHandTracker:
    """Mock HandTracker that returns data with FlatBuffer types."""
    def get_left_hand(self, session):
        """Return mock left hand data."""
        return MockHandData()
    
    def get_right_hand(self, session):
        """Return mock right hand data."""
        return MockHandData()


class MockHeadData:
    """Mock HeadPoseT using FlatBuffer types."""
    def __init__(self):
        position = Point(1.0, 1.5, 0.0)
        orientation = Quaternion(1.0, 0.0, 0.0, 0.0)
        self.pose = Pose(position, orientation)
        self.is_valid = True
        self.timestamp = Timestamp(987654321, 123456789)


class MockHeadTracker:
    """Mock HeadTracker that returns data with FlatBuffer types."""
    def get_head(self, session):
        """Return mock head pose."""
        return MockHeadData()


# ============================================================================
# Controllers Source Tests
# ============================================================================

class TestControllersSource:
    """Test ControllersSource functionality."""
    
    def test_controllers_source_creation(self):
        """Test that ControllersSource can be created with a mock tracker."""
        tracker = MockControllerTracker()
        session = MockSession()
        source = ControllersSource(tracker, session, name="controllers")
        
        assert source._name == "controllers"
        assert source._controller_tracker is tracker
        assert source._session is session
    
    def test_controllers_source_has_no_inputs(self):
        """Test that ControllersSource has no inputs."""
        tracker = MockControllerTracker()
        session = MockSession()
        source = ControllersSource(tracker, session, name="controllers")
        
        input_spec = source.input_spec()
        assert input_spec == {}
    
    def test_controllers_source_outputs(self):
        """Test that ControllersSource has correct outputs."""
        tracker = MockControllerTracker()
        session = MockSession()
        source = ControllersSource(tracker, session, name="controllers")
        
        output_spec = source.output_spec()
        assert "controller_left" in output_spec
        assert "controller_right" in output_spec
        assert len(output_spec) == 2
    
    def test_controllers_source_compute(self):
        """Test that ControllersSource compute reads tracker data correctly."""
        tracker = MockControllerTracker()
        session = MockSession()
        source = ControllersSource(tracker, session, name="controllers")
        
        # Execute the source
        outputs = source({})
        
        # Verify outputs exist
        assert "controller_left" in outputs
        assert "controller_right" in outputs
        
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
        
        # Verify scalar fields (trigger values) - use approximate comparison for floats
        assert left[10] == pytest.approx(0.5)  # trigger_value for left
        assert right[10] == pytest.approx(0.8)  # trigger_value for right
        
        # Verify is_active
        assert left[11] == True
        assert right[11] == True


# ============================================================================
# Hands Source Tests
# ============================================================================

class TestHandsSource:
    """Test HandsSource functionality."""
    
    def test_hands_source_creation(self):
        """Test that HandsSource can be created with a mock tracker."""
        tracker = MockHandTracker()
        session = MockSession()
        source = HandsSource(tracker, session, name="hands")
        
        assert source._name == "hands"
        assert source._hand_tracker is tracker
        assert source._session is session
    
    def test_hands_source_has_no_inputs(self):
        """Test that HandsSource has no inputs."""
        tracker = MockHandTracker()
        session = MockSession()
        source = HandsSource(tracker, session, name="hands")
        
        input_spec = source.input_spec()
        assert input_spec == {}
    
    def test_hands_source_outputs(self):
        """Test that HandsSource has correct outputs."""
        tracker = MockHandTracker()
        session = MockSession()
        source = HandsSource(tracker, session, name="hands")
        
        output_spec = source.output_spec()
        assert "hand_left" in output_spec
        assert "hand_right" in output_spec
        assert len(output_spec) == 2
    
    def test_hands_source_compute(self):
        """Test that HandsSource compute reads tracker data correctly."""
        tracker = MockHandTracker()
        session = MockSession()
        source = HandsSource(tracker, session, name="hands")
        
        # Execute the source
        outputs = source({})
        
        # Verify outputs exist
        assert "hand_left" in outputs
        assert "hand_right" in outputs
        
        # Verify left hand data
        left = outputs["hand_left"]
        positions = left[0]  # joint_positions
        orientations = left[1]  # joint_orientations
        radii = left[2]  # joint_radii
        valid = left[3]  # joint_valid
        is_active = left[4]  # is_active
        timestamp = left[5]  # timestamp
        
        # Check shapes
        assert positions.shape == (NUM_HAND_JOINTS, 3)
        assert orientations.shape == (NUM_HAND_JOINTS, 4)
        assert radii.shape == (NUM_HAND_JOINTS,)
        assert valid.shape == (NUM_HAND_JOINTS,)
        
        # Check first joint position (index 0)
        np.testing.assert_array_almost_equal(positions[0], [0.0, 0.0, 0.0])
        
        # Check second joint position (index 1)
        np.testing.assert_array_almost_equal(positions[1], [0.1, 0.2, 0.3])
        
        # Check orientations (XYZW format)
        np.testing.assert_array_almost_equal(orientations[0], [1.0, 0.0, 0.0, 0.0])
        
        # Check radii
        assert radii[0] == 0.01
        
        # Check validity
        assert valid[0] == 1  # True as uint8
        
        # Check is_active and timestamp
        assert is_active == True
        assert timestamp == 123456789
    
    def test_hands_source_handles_26_joints(self):
        """Test that HandsSource handles all 26 joints correctly."""
        tracker = MockHandTracker()
        session = MockSession()
        source = HandsSource(tracker, session, name="hands")
        
        outputs = source({})
        positions = outputs["hand_left"][0]
        
        # Verify we have all 26 joints
        assert positions.shape[0] == 26
        
        # Verify each joint has unique data based on index
        for i in range(NUM_HAND_JOINTS):
            expected_pos = [i * 0.1, i * 0.2, i * 0.3]
            np.testing.assert_array_almost_equal(positions[i], expected_pos)


# ============================================================================
# Head Source Tests
# ============================================================================

class TestHeadSource:
    """Test HeadSource functionality."""
    
    def test_head_source_creation(self):
        """Test that HeadSource can be created with a mock tracker."""
        tracker = MockHeadTracker()
        session = MockSession()
        source = HeadSource(tracker, session, name="head")
        
        assert source._name == "head"
        assert source._head_tracker is tracker
        assert source._session is session
    
    def test_head_source_has_no_inputs(self):
        """Test that HeadSource has no inputs."""
        tracker = MockHeadTracker()
        session = MockSession()
        source = HeadSource(tracker, session, name="head")
        
        input_spec = source.input_spec()
        assert input_spec == {}
    
    def test_head_source_outputs(self):
        """Test that HeadSource has correct outputs."""
        tracker = MockHeadTracker()
        session = MockSession()
        source = HeadSource(tracker, session, name="head")
        
        output_spec = source.output_spec()
        assert "head" in output_spec
        assert len(output_spec) == 1
    
    def test_head_source_compute(self):
        """Test that HeadSource compute reads tracker data correctly."""
        tracker = MockHeadTracker()
        session = MockSession()
        source = HeadSource(tracker, session, name="head")
        
        # Execute the source
        outputs = source({})
        
        # Verify output exists
        assert "head" in outputs
        
        # Verify head data
        head = outputs["head"]
        position = head[0]  # head_position
        orientation = head[1]  # head_orientation
        is_valid = head[2]  # head_is_valid
        timestamp = head[3]  # head_timestamp
        
        # Check shapes
        assert position.shape == (3,)
        assert orientation.shape == (4,)
        
        # Check values (XYZW format)
        np.testing.assert_array_almost_equal(position, [1.0, 1.5, 0.0])
        np.testing.assert_array_almost_equal(orientation, [1.0, 0.0, 0.0, 0.0])
        assert is_valid == True
        assert timestamp == 987654321
    
    def test_head_source_with_different_pose(self):
        """Test HeadSource with a custom head pose."""
        # Create a custom head tracker with different values
        class CustomHeadTracker:
            def get_head(self, session):
                data = type('obj', (object,), {})()
                data.pose = Pose(Point(2.0, 3.0, 4.0), Quaternion(0.707, 0.0, 0.707, 0.0))
                data.is_valid = False
                data.timestamp = Timestamp(111, 222)
                return data
        
        tracker = CustomHeadTracker()
        session = MockSession()
        source = HeadSource(tracker, session, name="head")
        
        outputs = source({})
        head = outputs["head"]
        
        # Verify custom values
        np.testing.assert_array_almost_equal(head[0], [2.0, 3.0, 4.0])
        np.testing.assert_array_almost_equal(head[1], [0.707, 0.0, 0.707, 0.0])
        assert head[2] == False
        assert head[3] == 111


# ============================================================================
# Integration Tests
# ============================================================================

class TestSourcesIntegration:
    """Test that sources can be used in retargeting graphs."""
    
    def test_head_source_in_graph(self):
        """Test that HeadSource can be used as input to another retargeter."""
        from teleopcore.retargeting_engine.interface import BaseRetargeter, TensorGroupType
        from teleopcore.retargeting_engine.tensor_types import HeadPose, FloatType
        
        # Create a simple retargeter that uses head data
        class HeadHeightExtractor(BaseRetargeter):
            """Extract Y coordinate from head position."""
            def input_spec(self):
                return {"head": HeadPose()}
            
            def output_spec(self):
                return {"height": TensorGroupType("height", [FloatType("value")])}
            
            def compute(self, inputs, outputs):
                head_position = inputs["head"][0]
                outputs["height"][0] = float(head_position[1])  # Y coordinate
        
        # Create source and retargeter
        head_tracker = MockHeadTracker()
        session = MockSession()
        head_source = HeadSource(head_tracker, session, name="head")
        height_extractor = HeadHeightExtractor(name="extractor")
        
        # Connect them
        connected = height_extractor.connect({
            "head": head_source.output("head")
        })
        
        # Execute the graph
        result = connected({"head": {}})
        
        # Verify the height was extracted (Y = 1.5 from MockHeadData)
        assert result["height"][0] == 1.5
    
    def test_hands_source_in_graph(self):
        """Test that HandsSource can be used as input to another retargeter."""
        from teleopcore.retargeting_engine.interface import BaseRetargeter, TensorGroupType
        from teleopcore.retargeting_engine.tensor_types import HandInput, FloatType
        
        # Create a simple retargeter that counts active hands
        class HandCounter(BaseRetargeter):
            """Count how many hands are active."""
            def input_spec(self):
                return {
                    "hand_left": HandInput(),
                    "hand_right": HandInput(),
                }
            
            def output_spec(self):
                return {"count": TensorGroupType("count", [FloatType("value")])}
            
            def compute(self, inputs, outputs):
                count = 0
                if inputs["hand_left"][4]:  # is_active
                    count += 1
                if inputs["hand_right"][4]:  # is_active
                    count += 1
                outputs["count"][0] = float(count)
        
        # Create source and retargeter
        hand_tracker = MockHandTracker()
        session = MockSession()
        hands_source = HandsSource(hand_tracker, session, name="hands")
        counter = HandCounter(name="counter")
        
        # Connect them
        connected = counter.connect({
            "hand_left": hands_source.output("hand_left"),
            "hand_right": hands_source.output("hand_right"),
        })
        
        # Execute the graph
        result = connected({"hands": {}})
        
        # Verify both hands are active
        assert result["count"][0] == 2.0
