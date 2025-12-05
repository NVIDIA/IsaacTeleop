# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for example retargeting modules.

Demonstrates usage of SampleRetargeter and GripperRetargeter.
"""

import pytest
import numpy as np
from typing import Dict

from .. import (
    BaseRetargeter,
    RetargeterIO,
    TensorGroupType,
    TensorGroup,
    FloatType,
    BoolType,
    NDArrayType,
    DLDataType,
    DLDeviceType,
)
from ..examples import SampleRetargeter, GripperRetargeter


# ============================================================================
# Helper Source Modules
# ============================================================================

class ValueSource(BaseRetargeter):
    """Source module that outputs configurable x and y values."""
    
    def __init__(self, name: str, x: float = 0.0, y: float = 0.0):
        self.x = x
        self.y = y
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        return {}  # No inputs - this is a source
    
    def output_spec(self) -> RetargeterIO:
        return {
            "values": TensorGroupType("values", [
                FloatType("x"),
                FloatType("y")
            ])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        outputs["values"][0] = self.x
        outputs["values"][1] = self.y


class ParamSource(BaseRetargeter):
    """Source module that outputs scale and offset parameters."""
    
    def __init__(self, name: str, scale: float = 1.0, offset: float = 0.0):
        self.scale = scale
        self.offset = offset
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        return {}  # No inputs - this is a source
    
    def output_spec(self) -> RetargeterIO:
        return {
            "params": TensorGroupType("params", [
                FloatType("scale"),
                FloatType("offset")
            ])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        outputs["params"][0] = self.scale
        outputs["params"][1] = self.offset


class ControllerSource(BaseRetargeter):
    """Source module that outputs controller data."""
    
    def __init__(
        self,
        name: str,
        trigger_value: float = 0.0,
        is_active: bool = True,
        side: str = "left"
    ):
        self.trigger_value = trigger_value
        self.is_active = is_active
        self.side = side
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        return {}  # No inputs - this is a source
    
    def output_spec(self) -> RetargeterIO:
        controller_name = f"controller_{self.side}"
        return {
            controller_name: TensorGroupType(controller_name, [
                NDArrayType(f"{self.side}_controller_grip_position", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32),
                NDArrayType(f"{self.side}_controller_grip_orientation", shape=(4,), dtype=DLDataType.FLOAT, dtype_bits=32),
                NDArrayType(f"{self.side}_controller_aim_position", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32),
                NDArrayType(f"{self.side}_controller_aim_orientation", shape=(4,), dtype=DLDataType.FLOAT, dtype_bits=32),
                FloatType(f"{self.side}_controller_primary_click"),
                FloatType(f"{self.side}_controller_secondary_click"),
                FloatType(f"{self.side}_controller_thumbstick_x"),
                FloatType(f"{self.side}_controller_thumbstick_y"),
                FloatType(f"{self.side}_controller_thumbstick_click"),
                FloatType(f"{self.side}_controller_squeeze_value"),
                FloatType(f"{self.side}_controller_trigger_value"),
                BoolType(f"{self.side}_controller_is_active"),
            ])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        controller_name = f"controller_{self.side}"
        output = outputs[controller_name]
        
        # Set array values (positions and orientations)
        output[0] = np.array([0.0, 0.0, 0.0], dtype=np.float32)  # grip_position
        output[1] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)  # grip_orientation
        output[2] = np.array([0.0, 0.0, 0.0], dtype=np.float32)  # aim_position
        output[3] = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)  # aim_orientation
        
        # Set scalar button/axis values
        output[4] = 0.0  # primary_click
        output[5] = 0.0  # secondary_click
        output[6] = 0.0  # thumbstick_x
        output[7] = 0.0  # thumbstick_y
        output[8] = 0.0  # thumbstick_click
        output[9] = 0.0  # squeeze_value
        output[10] = self.trigger_value  # trigger_value
        output[11] = self.is_active  # is_active


# ============================================================================
# Tests for SampleRetargeter
# ============================================================================

def test_sample_retargeter_basic():
    """Test basic SampleRetargeter functionality."""
    # Create sources
    values = ValueSource("values", x=2.0, y=3.0)
    params = ParamSource("params", scale=2.0, offset=1.0)
    
    # Create retargeter
    sample = SampleRetargeter("sample")
    
    # Connect inputs
    connected = sample.connect({
        "values": values.output("values"),
        "params": params.output("params")
    })
    
    # Execute
    result = connected()
    
    # Verify outputs
    # scaled_x = 2.0 * 2.0 + 1.0 = 5.0
    # scaled_y = 3.0 * 2.0 + 1.0 = 7.0
    # sum = 5.0 + 7.0 = 12.0
    assert result["results"][0] == 5.0
    assert result["results"][1] == 7.0
    assert result["results"][2] == 12.0


def test_sample_retargeter_zero_scale():
    """Test SampleRetargeter with zero scale."""
    values = ValueSource("values", x=10.0, y=20.0)
    params = ParamSource("params", scale=0.0, offset=5.0)
    
    sample = SampleRetargeter("sample")
    connected = sample.connect({
        "values": values.output("values"),
        "params": params.output("params")
    })
    
    result = connected()
    
    # scaled_x = 10.0 * 0.0 + 5.0 = 5.0
    # scaled_y = 20.0 * 0.0 + 5.0 = 5.0
    # sum = 5.0 + 5.0 = 10.0
    assert result["results"][0] == 5.0
    assert result["results"][1] == 5.0
    assert result["results"][2] == 10.0


def test_sample_retargeter_negative_values():
    """Test SampleRetargeter with negative values."""
    values = ValueSource("values", x=-1.0, y=-2.0)
    params = ParamSource("params", scale=3.0, offset=-0.5)
    
    sample = SampleRetargeter("sample")
    connected = sample.connect({
        "values": values.output("values"),
        "params": params.output("params")
    })
    
    result = connected()
    
    # scaled_x = -1.0 * 3.0 + (-0.5) = -3.5
    # scaled_y = -2.0 * 3.0 + (-0.5) = -6.5
    # sum = -3.5 + (-6.5) = -10.0
    assert result["results"][0] == -3.5
    assert result["results"][1] == -6.5
    assert result["results"][2] == -10.0


# ============================================================================
# Tests for GripperRetargeter
# ============================================================================

def test_gripper_retargeter_both_active():
    """Test GripperRetargeter with both controllers active."""
    left = ControllerSource("left_ctrl", trigger_value=0.5, is_active=True, side="left")
    right = ControllerSource("right_ctrl", trigger_value=0.8, is_active=True, side="right")
    
    gripper = GripperRetargeter("gripper")
    connected = gripper.connect({
        "controller_left": left.output("controller_left"),
        "controller_right": right.output("controller_right")
    })
    
    result = connected()
    
    # Left gripper should be 0.5, right gripper should be 0.8
    assert result["gripper_left"][0] == 0.5
    assert result["gripper_right"][0] == 0.8


def test_gripper_retargeter_left_inactive():
    """Test GripperRetargeter with left controller inactive."""
    left = ControllerSource("left_ctrl", trigger_value=0.5, is_active=False, side="left")
    right = ControllerSource("right_ctrl", trigger_value=0.8, is_active=True, side="right")
    
    gripper = GripperRetargeter("gripper")
    connected = gripper.connect({
        "controller_left": left.output("controller_left"),
        "controller_right": right.output("controller_right")
    })
    
    result = connected()
    
    # Left gripper should be 0.0 (inactive), right gripper should be 0.8
    assert result["gripper_left"][0] == 0.0
    assert result["gripper_right"][0] == 0.8


def test_gripper_retargeter_both_inactive():
    """Test GripperRetargeter with both controllers inactive."""
    left = ControllerSource("left_ctrl", trigger_value=0.5, is_active=False, side="left")
    right = ControllerSource("right_ctrl", trigger_value=0.8, is_active=False, side="right")
    
    gripper = GripperRetargeter("gripper")
    connected = gripper.connect({
        "controller_left": left.output("controller_left"),
        "controller_right": right.output("controller_right")
    })
    
    result = connected()
    
    # Both grippers should be 0.0 (inactive)
    assert result["gripper_left"][0] == 0.0
    assert result["gripper_right"][0] == 0.0


def test_gripper_retargeter_full_trigger():
    """Test GripperRetargeter with full trigger values."""
    left = ControllerSource("left_ctrl", trigger_value=1.0, is_active=True, side="left")
    right = ControllerSource("right_ctrl", trigger_value=1.0, is_active=True, side="right")
    
    gripper = GripperRetargeter("gripper")
    connected = gripper.connect({
        "controller_left": left.output("controller_left"),
        "controller_right": right.output("controller_right")
    })
    
    result = connected()
    
    # Both grippers should be 1.0 (fully closed)
    assert result["gripper_left"][0] == 1.0
    assert result["gripper_right"][0] == 1.0


def test_gripper_retargeter_zero_trigger():
    """Test GripperRetargeter with zero trigger values."""
    left = ControllerSource("left_ctrl", trigger_value=0.0, is_active=True, side="left")
    right = ControllerSource("right_ctrl", trigger_value=0.0, is_active=True, side="right")
    
    gripper = GripperRetargeter("gripper")
    connected = gripper.connect({
        "controller_left": left.output("controller_left"),
        "controller_right": right.output("controller_right")
    })
    
    result = connected()
    
    # Both grippers should be 0.0 (fully open)
    assert result["gripper_left"][0] == 0.0
    assert result["gripper_right"][0] == 0.0

