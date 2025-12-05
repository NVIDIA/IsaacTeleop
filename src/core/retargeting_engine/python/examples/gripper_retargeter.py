# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Gripper Retargeter Module.

Takes controller inputs and outputs gripper control values based on trigger values.

Note: This retargeter uses the standard controller_type() definitions which include
NDArray types for poses. NDArray inputs would need to be converted using np.from_dlpack()
if you need to process them (though this simple example only uses scalar trigger values).
"""

from typing import Dict
from ..interface.retargeting_module import BaseRetargeter, RetargeterIO
from ..interface.tensor_group_type import TensorGroupType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import FloatType, ControllerInput


class GripperRetargeter(BaseRetargeter):
    """
    Gripper retargeter that uses controller triggers to control two robot grippers.
    
    Inputs:
        - "controller_left": left controller with trigger_value and is_active
        - "controller_right": right controller with trigger_value and is_active
    
    Outputs:
        - "gripper_left": left gripper value (0.0 = open, 1.0 = closed)
        - "gripper_right": right gripper value (0.0 = open, 1.0 = closed)
    """
    
    def __init__(self, name: str) -> None:
        """
        Initialize gripper retargeter.
        
        Args:
            name: Name identifier for this retargeter (must be unique)
        """
        super().__init__(name=name)
    
    def input_spec(self) -> RetargeterIO:
        """Define input collections for controllers using standard types."""
        return {
            "controller_left": ControllerInput(),
            "controller_right": ControllerInput()
        }
    
    def output_spec(self) -> RetargeterIO:
        """Define output collections for left and right grippers."""
        return {
            "gripper_left": TensorGroupType("gripper_left", [FloatType("left_gripper_value")]),
            "gripper_right": TensorGroupType("gripper_right", [FloatType("right_gripper_value")])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Execute the gripper retargeting transformation.
        
        This method demonstrates working with standard controller types that include
        NDArray fields. For this simple gripper control, we only use the scalar
        trigger_value and is_active fields. If you needed to process the pose data,
        you would convert using np.from_dlpack():
            grip_pos = np.from_dlpack(left_controller_group[0])
        
        Args:
            inputs: Dict with "controller_left" and "controller_right" TensorGroups
            outputs: Dict with "gripper_left" and "gripper_right" TensorGroups
        """
        left_controller_group = inputs["controller_left"]
        right_controller_group = inputs["controller_right"]
        left_gripper_group = outputs["gripper_left"]
        right_gripper_group = outputs["gripper_right"]
        
        # Compute left gripper
        # Indices 4-11 are scalar types (FloatType and BoolType)
        is_active_left = left_controller_group[11]  # is_active at index 11 (BoolType)
        trigger_left = left_controller_group[10] if is_active_left else 0.0  # trigger_value at index 10 (FloatType)
        left_gripper_group[0] = float(trigger_left)
        
        # Compute right gripper
        is_active_right = right_controller_group[11]  # is_active at index 11 (BoolType)
        trigger_right = right_controller_group[10] if is_active_right else 0.0  # trigger_value at index 10 (FloatType)
        right_gripper_group[0] = float(trigger_right)

