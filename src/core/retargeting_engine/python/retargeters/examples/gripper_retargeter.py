"""
Gripper Retargeter Node.

Takes controller inputs and outputs gripper control values based on trigger values.
"""

from typing import List, Optional
import numpy as np
from ...interface.retargeter_node import RetargeterNode
from ...interface.tensor_collection import TensorCollection
from ...interface.tensor_group import TensorGroup
from ...interface.output_selector import OutputSelector
from ...tensor_types.examples.scalar_types import BoolType, FloatType
from ...tensor_types.examples.numpy_types import NumpyArrayType


class GripperRetargeter(RetargeterNode):
    """
    Gripper retargeter that uses controller triggers to control two robot grippers.
    
    Inputs:
        - controller_left: left controller with trigger_value and is_active
        - controller_right: right controller with trigger_value and is_active
    
    Outputs:
        - gripper_left: left gripper value (0.0 = open, 1.0 = closed)
        - gripper_right: right gripper value (0.0 = open, 1.0 = closed)
    """
    
    def __init__(self, name: str = "gripper_retargeter") -> None:
        """
        Initialize gripper retargeter.
        
        Args:
            name: Name identifier for this retargeter
        """
        super().__init__(name=name)
    
    def connect_controllers(self, controller_left: OutputSelector, controller_right: OutputSelector) -> None:
        """
        Connect the gripper retargeter to its input sources.
        
        Args:
            controller_left: OutputSelector for left controller input
            controller_right: OutputSelector for right controller input
        """
        self.connect([controller_left, controller_right])
    
    def _define_inputs(self) -> List[TensorCollection]:
        """Define input collections for controllers."""
        left_controller = TensorCollection("controller_left", [
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
        
        right_controller = TensorCollection("controller_right", [
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
        
        return [left_controller, right_controller]
    
    def _define_outputs(self) -> List[TensorCollection]:
        """Define output collections for left and right grippers."""
        return [
            TensorCollection("gripper_left", [FloatType("left_gripper_value")]),
            TensorCollection("gripper_right", [FloatType("right_gripper_value")])
        ]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        """
        Execute the gripper retargeting transformation.
        
        Args:
            inputs: List with two input TensorGroups [left_controller, right_controller]
            outputs: List with two output TensorGroups [left_gripper, right_gripper]
            output_mask: Optional mask for which outputs to compute. If None, compute all.
        """
        left_controller_group = inputs[0]
        right_controller_group = inputs[1]
        left_gripper_group = outputs[0]
        right_gripper_group = outputs[1]
        
        # Compute left gripper (if not masked)
        if output_mask is None or output_mask[0]:
            # Get trigger value if controller is active, otherwise 0.0
            is_active = left_controller_group[11]  # is_active at index 11
            trigger = left_controller_group[10] if is_active else 0.0  # trigger_value at index 10
            left_gripper_group[0] = float(trigger)
        
        # Compute right gripper (if not masked)
        if output_mask is None or output_mask[1]:
            # Get trigger value if controller is active, otherwise 0.0
            is_active = right_controller_group[11]  # is_active at index 11
            trigger = right_controller_group[10] if is_active else 0.0  # trigger_value at index 10
            right_gripper_group[0] = float(trigger)
    
    # Semantic output selectors
    def left(self) -> OutputSelector:
        """Get the left gripper output selector."""
        return self.output(0)
    
    def right(self) -> OutputSelector:
        """Get the right gripper output selector."""
        return self.output(1)

