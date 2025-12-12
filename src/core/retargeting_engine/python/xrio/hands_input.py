"""
Hands Input Node - wraps XRIO HandTracker for both hands.

Converts HandData from XRIO into two TensorCollections (left and right hands).
Requires a trigger input from XrioUpdateNode to ensure data freshness.
"""

from typing import Any, List, Optional
import numpy as np
from ..interface.retargeter_node import RetargeterNode
from ..interface.tensor_collection import TensorCollection
from ..interface.tensor_group import TensorGroup
from ..interface.output_selector import OutputSelector
from ..tensor_types.examples.scalar_types import BoolType, IntType
from ..tensor_types.examples.numpy_types import NumpyArrayType


class HandsInput(RetargeterNode):
    """
    Input node for XRIO HandTracker that provides both hands as separate collections.
    
    Provides joint positions, orientations, radii, validity flags, 
    hand active state, and timestamp for both left and right hands
    as two separate TensorCollections.
    
    This node creates and manages its own HandTracker instance.
    
    **Important**: Requires a trigger input from XrioUpdateNode to ensure tracker
    data is fresh before reading.
    
    Usage:
        builder = xrio.XrioSessionBuilder()
        xrio_update = XrioUpdateNode(builder, app_name="MyApp")
        hands = HandsInput(builder, trigger=xrio_update.trigger())
    """
    
    def __init__(self, xrio_session_builder: Any, name: str = "hands") -> None:
        """
        Initialize hands input node and create HandTracker.
        
        Args:
            xrio_session_builder: xrio.XrioSessionBuilder to register the tracker with
            name: Name identifier for this input (default: "hands")
        """
        # Import xrio and create tracker
        try:
            import teleopcore.xrio as xrio
            self._num_joints = xrio.NUM_JOINTS
        except (ImportError, AttributeError):
            self._num_joints = 26  # XR_HAND_JOINT_COUNT_EXT fallback
            import teleopcore.xrio as xrio
        
        # Create and register tracker
        self._hand_tracker = xrio.HandTracker()
        xrio_session_builder.add_tracker(self._hand_tracker)
        
        super().__init__(name)
    
    def connect_trigger(self, trigger: OutputSelector) -> None:
        """
        Connect the hands input to its trigger source.
        
        Args:
            trigger: OutputSelector from XrioUpdateNode to ensure data freshness
        """
        self.connect([trigger])
    
    def _define_inputs(self) -> List[TensorCollection]:
        """Define trigger input from XrioUpdateNode."""
        return [
            TensorCollection("trigger", [
                BoolType("update_success")
            ])
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        """Define hands input output structure (two collections: left and right)."""
        left_collection = TensorCollection("hand_left", [
            NumpyArrayType(
                "left_hand_joint_positions",
                dtype=np.dtype('float32'),
                shape=(self._num_joints, 3)
            ),
            NumpyArrayType(
                "left_hand_joint_orientations",
                dtype=np.dtype('float32'),
                shape=(self._num_joints, 4)
            ),
            NumpyArrayType(
                "left_hand_joint_radii",
                dtype=np.dtype('float32'),
                shape=(self._num_joints,)
            ),
            NumpyArrayType(
                "left_hand_joint_valid",
                dtype=np.dtype('bool'),
                shape=(self._num_joints,)
            ),
            BoolType("left_hand_is_active"),
            IntType("left_hand_timestamp"),
        ])
        
        right_collection = TensorCollection("hand_right", [
            NumpyArrayType(
                "right_hand_joint_positions",
                dtype=np.dtype('float32'),
                shape=(self._num_joints, 3)
            ),
            NumpyArrayType(
                "right_hand_joint_orientations",
                dtype=np.dtype('float32'),
                shape=(self._num_joints, 4)
            ),
            NumpyArrayType(
                "right_hand_joint_radii",
                dtype=np.dtype('float32'),
                shape=(self._num_joints,)
            ),
            NumpyArrayType(
                "right_hand_joint_valid",
                dtype=np.dtype('bool'),
                shape=(self._num_joints,)
            ),
            BoolType("right_hand_is_active"),
            IntType("right_hand_timestamp"),
        ])
        
        return [left_collection, right_collection]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        """
        Read hand tracking data from XRIO trackers.
        
        Args:
            inputs: List with one TensorGroup containing the trigger signal
            outputs: List with two TensorGroups [left_hand, right_hand]
            output_mask: Optional mask for which outputs to compute
        """
        # Trigger is in inputs[0], but we don't need to check it - 
        # the fact that we're executing means the dependency was satisfied
        
        # Update left hand (output 0)
        if output_mask is None or output_mask[0]:
            left_data = self._hand_tracker.get_left_hand()
            self._update_hand_data(outputs[0], left_data)
        
        # Update right hand (output 1)
        if output_mask is None or output_mask[1]:
            right_data = self._hand_tracker.get_right_hand()
            self._update_hand_data(outputs[1], right_data)
    
    def _update_hand_data(self, group: TensorGroup, hand_data: Any) -> None:
        """Helper to update hand data for a single hand."""
        # Pre-allocate arrays
        positions = np.zeros((self._num_joints, 3), dtype=np.float32)
        orientations = np.zeros((self._num_joints, 4), dtype=np.float32)
        radii = np.zeros(self._num_joints, dtype=np.float32)
        valid = np.zeros(self._num_joints, dtype=bool)
        
        # Extract joint data
        for i in range(hand_data.num_joints):
            joint = hand_data.get_joint(i)
            positions[i] = joint.position
            orientations[i] = joint.orientation
            radii[i] = joint.radius
            valid[i] = joint.is_valid
        
        # Update tensor group using index-based access
        group[0] = positions
        group[1] = orientations
        group[2] = radii
        group[3] = valid
        group[4] = hand_data.is_active
        group[5] = int(hand_data.timestamp)
    
    # Semantic output selectors
    def left(self) -> OutputSelector:
        """Get the left hand output selector."""
        return self.output(0)
    
    def right(self) -> OutputSelector:
        """Get the right hand output selector."""
        return self.output(1)

