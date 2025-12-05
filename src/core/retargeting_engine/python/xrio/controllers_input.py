"""
Controllers Input Node - wraps XRIO ControllerTracker for both controllers.

Converts ControllerSnapshot data from XRIO into two TensorCollections (left and right controllers).
Requires a trigger input from XrioUpdateNode to ensure data freshness.
"""

from typing import Any, List, Optional
import numpy as np
import teleopcore.xrio as xrio
from ..interface.retargeter_node import RetargeterNode
from ..interface.tensor_collection import TensorCollection
from ..interface.tensor_group import TensorGroup
from ..interface.output_selector import OutputSelector
from ..tensor_types.examples.scalar_types import BoolType, FloatType
from ..tensor_types.examples.numpy_types import NumpyArrayType


class ControllersInput(RetargeterNode):
    """
    Input node for XRIO ControllerTracker that provides both controllers as separate collections.
    
    Provides grip pose, aim pose, and controller input states 
    (buttons, triggers, thumbstick) for both left and right controllers
    as two separate TensorCollections.
    
    This node creates and manages its own ControllerTracker instance.
    
    **Important**: Requires a trigger input from XrioUpdateNode to ensure tracker
    data is fresh before reading.
    
    Usage:
        builder = xrio.XrioSessionBuilder()
        xrio_update = XrioUpdateNode(builder, app_name="MyApp")
        controllers = ControllersInput(builder, trigger=xrio_update.trigger())
    """
    
    def __init__(self, xrio_session_builder: Any, name: str = "controllers") -> None:
        """
        Initialize controllers input node and create ControllerTracker.
        
        Args:
            xrio_session_builder: xrio.XrioSessionBuilder to register the tracker with
            name: Name identifier for this input (default: "controllers")
        """
        # Import Hand enum from xrio
        try:
            import teleopcore.xrio
            self._hand_left = teleopcore.xrio.Hand.Left
            self._hand_right = teleopcore.xrio.Hand.Right
        except (ImportError, AttributeError):
            raise ImportError("Failed to import Hand enum from teleopcore.xrio")
        
        # Create and register tracker
        self._controller_tracker = xrio.ControllerTracker()
        xrio_session_builder.add_tracker(self._controller_tracker)
        
        super().__init__(name)
    
    def connect_trigger(self, trigger: OutputSelector) -> None:
        """
        Connect the controllers input to its trigger source.
        
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
        """Define controllers input output structure (two collections: left and right)."""
        left_collection = TensorCollection("controller_left", [
            NumpyArrayType("left_controller_grip_position", dtype=np.dtype('float32'), shape=(3,)),
            NumpyArrayType("left_controller_grip_orientation", dtype=np.dtype('float32'), shape=(4,)),
            NumpyArrayType("left_controller_aim_position", dtype=np.dtype('float32'), shape=(3,)),
            NumpyArrayType("left_controller_aim_orientation", dtype=np.dtype('float32'), shape=(4,)),
            FloatType("left_controller_primary_click"),
            FloatType("left_controller_secondary_click"),
            FloatType("left_controller_thumbstick_x"),
            FloatType("left_controller_thumbstick_y"),
            FloatType("left_controller_thumbstick_click"),
            FloatType("left_controller_squeeze_value"),
            FloatType("left_controller_trigger_value"),
            BoolType("left_controller_is_active"),
        ])
        
        right_collection = TensorCollection("controller_right", [
            NumpyArrayType("right_controller_grip_position", dtype=np.dtype('float32'), shape=(3,)),
            NumpyArrayType("right_controller_grip_orientation", dtype=np.dtype('float32'), shape=(4,)),
            NumpyArrayType("right_controller_aim_position", dtype=np.dtype('float32'), shape=(3,)),
            NumpyArrayType("right_controller_aim_orientation", dtype=np.dtype('float32'), shape=(4,)),
            FloatType("right_controller_primary_click"),
            FloatType("right_controller_secondary_click"),
            FloatType("right_controller_thumbstick_x"),
            FloatType("right_controller_thumbstick_y"),
            FloatType("right_controller_thumbstick_click"),
            FloatType("right_controller_squeeze_value"),
            FloatType("right_controller_trigger_value"),
            BoolType("right_controller_is_active"),
        ])
        
        return [left_collection, right_collection]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        """
        Read controller tracking data from XRIO trackers.
        
        Args:
            inputs: List with one TensorGroup containing the trigger signal
            outputs: List with two TensorGroups [left_controller, right_controller]
            output_mask: Optional mask for which outputs to compute
        """
        # Trigger is in inputs[0], but we don't need to check it - 
        # the fact that we're executing means the dependency was satisfied
        
        # Update left controller (output 0)
        if output_mask is None or output_mask[0]:
            left_snapshot = self._controller_tracker.get_snapshot(self._hand_left)
            self._update_controller_data(outputs[0], left_snapshot)
        
        # Update right controller (output 1)
        if output_mask is None or output_mask[1]:
            right_snapshot = self._controller_tracker.get_snapshot(self._hand_right)
            self._update_controller_data(outputs[1], right_snapshot)
    
    def _update_controller_data(self, group: TensorGroup, snapshot: Any) -> None:
        """Helper to update controller data for a single controller."""
        # Extract pose data
        grip_pos = np.array(snapshot.grip_pose.position, dtype=np.float32)
        grip_ori = np.array(snapshot.grip_pose.orientation, dtype=np.float32)
        aim_pos = np.array(snapshot.aim_pose.position, dtype=np.float32)
        aim_ori = np.array(snapshot.aim_pose.orientation, dtype=np.float32)
        
        # Extract input state
        inputs = snapshot.inputs
        
        # Update tensor group using index-based access
        group[0] = grip_pos
        group[1] = grip_ori
        group[2] = aim_pos
        group[3] = aim_ori
        group[4] = float(inputs[xrio.ControllerInput.PrimaryClick])
        group[5] = float(inputs[xrio.ControllerInput.SecondaryClick])
        group[6] = float(inputs[xrio.ControllerInput.ThumbstickX])
        group[7] = float(inputs[xrio.ControllerInput.ThumbstickY])
        group[8] = float(inputs[xrio.ControllerInput.ThumbstickClick])
        group[9] = float(inputs[xrio.ControllerInput.SqueezeValue])
        group[10] = float(inputs[xrio.ControllerInput.TriggerValue])
        group[11] = snapshot.is_active
    
    # Semantic output selectors
    def left(self) -> OutputSelector:
        """Get the left controller output selector."""
        return self.output(0)
    
    def right(self) -> OutputSelector:
        """Get the right controller output selector."""
        return self.output(1)

