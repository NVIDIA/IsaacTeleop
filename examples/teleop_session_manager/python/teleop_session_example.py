#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Hand and Controller Velocity Tracker Example with TeleopSessionManager

Demonstrates using TeleopSession with velocity tracking.

This example shows:
1. Computing velocity from wrist and controller position changes
2. Using TeleopSession with synthetic hands plugin
3. Displaying velocity data
"""

import sys
import time
import numpy as np
from pathlib import Path
from typing import Dict, Optional

from teleopcore.retargeting_engine.deviceio_source_nodes import HandsSource, ControllersSource
from teleopcore.teleop_session_manager import TeleopSession, TeleopSessionConfig, PluginConfig
from teleopcore.retargeting_engine.interface import BaseRetargeter
from teleopcore.retargeting_engine.tensor_types import HandInput, ControllerInput
from teleopcore.retargeting_engine.interface.tensor_group_type import TensorGroupType
from teleopcore.retargeting_engine.interface.tensor_group import TensorGroup
from teleopcore.retargeting_engine.tensor_types import FloatType


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"


# ==============================================================================
# Velocity Tracker
# ==============================================================================

class VelocityTracker(BaseRetargeter):
    """Computes velocity from hand wrist and controller position changes."""
    
    def __init__(self, name: str):
        super().__init__(name)
        
        # Store previous positions for velocity computation
        self._prev_hand_left: Optional[np.ndarray] = None
        self._prev_hand_right: Optional[np.ndarray] = None
        self._prev_ctrl_left: Optional[np.ndarray] = None
        self._prev_ctrl_right: Optional[np.ndarray] = None
        self._prev_time: Optional[float] = None
    
    def input_spec(self):
        return {
            "hand_left": HandInput(),
            "hand_right": HandInput(),
            "controller_left": ControllerInput(),
            "controller_right": ControllerInput(),
        }
    
    def output_spec(self):
        return {
            "hand_velocity_left": TensorGroupType("hand_velocity_left", [FloatType("magnitude")]),
            "hand_velocity_right": TensorGroupType("hand_velocity_right", [FloatType("magnitude")]),
            "controller_velocity_left": TensorGroupType("controller_velocity_left", [FloatType("magnitude")]),
            "controller_velocity_right": TensorGroupType("controller_velocity_right", [FloatType("magnitude")]),
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        # Get hand wrist positions (first joint of hand_joint_positions)
        hand_left_positions = inputs["hand_left"][0]  # (26, 3) array
        hand_right_positions = inputs["hand_right"][0]
        
        hand_left_wrist = np.array([hand_left_positions[0][0], hand_left_positions[0][1], hand_left_positions[0][2]])
        hand_right_wrist = np.array([hand_right_positions[0][0], hand_right_positions[0][1], hand_right_positions[0][2]])
        
        # Get controller positions (first tensor in ControllerInput is position array)
        ctrl_left_pos = inputs["controller_left"][0]  # (3,) array
        ctrl_right_pos = inputs["controller_right"][0]
        
        ctrl_left = np.array([ctrl_left_pos[0], ctrl_left_pos[1], ctrl_left_pos[2]])
        ctrl_right = np.array([ctrl_right_pos[0], ctrl_right_pos[1], ctrl_right_pos[2]])
        
        current_time = time.time()
        
        # Compute velocity if we have previous data
        if self._prev_hand_left is not None and self._prev_time is not None:
            dt = current_time - self._prev_time
            if dt > 0:
                hand_left_vel = float(np.linalg.norm(hand_left_wrist - self._prev_hand_left) / dt)
                hand_right_vel = float(np.linalg.norm(hand_right_wrist - self._prev_hand_right) / dt)
                ctrl_left_vel = float(np.linalg.norm(ctrl_left - self._prev_ctrl_left) / dt)
                ctrl_right_vel = float(np.linalg.norm(ctrl_right - self._prev_ctrl_right) / dt)
                
                outputs["hand_velocity_left"][0] = hand_left_vel
                outputs["hand_velocity_right"][0] = hand_right_vel
                outputs["controller_velocity_left"][0] = ctrl_left_vel
                outputs["controller_velocity_right"][0] = ctrl_right_vel
            else:
                outputs["hand_velocity_left"][0] = 0.0
                outputs["hand_velocity_right"][0] = 0.0
                outputs["controller_velocity_left"][0] = 0.0
                outputs["controller_velocity_right"][0] = 0.0
        else:
            # First frame, no velocity yet
            outputs["hand_velocity_left"][0] = 0.0
            outputs["hand_velocity_right"][0] = 0.0
            outputs["controller_velocity_left"][0] = 0.0
            outputs["controller_velocity_right"][0] = 0.0
        
        # Store current positions for next frame
        self._prev_hand_left = hand_left_wrist
        self._prev_hand_right = hand_right_wrist
        self._prev_ctrl_left = ctrl_left
        self._prev_ctrl_right = ctrl_right
        self._prev_time = current_time


def main():
    # ==================================================================
    # Build Pipeline
    # ==================================================================
    
    hands = HandsSource(name="hands")
    controllers = ControllersSource(name="controllers")
    
    tracker = VelocityTracker(name="velocity_tracker")
    pipeline = tracker.connect({
        "hand_left": hands.output("hand_left"),
        "hand_right": hands.output("hand_right"),
        "controller_left": controllers.output("controller_left"),
        "controller_right": controllers.output("controller_right"),
    })
    
    # ==================================================================
    # Create TeleopSession with synthetic hands plugin
    # ==================================================================
    
    config = TeleopSessionConfig(
        app_name="VelocityTrackerExample",
        pipeline=pipeline,
        plugins=[
            PluginConfig(
                plugin_name="controller_synthetic_hands",
                plugin_root_id="synthetic_hands",
                search_paths=[PLUGIN_ROOT_DIR],
            )
        ],
    )
    
    with TeleopSession(config) as session:
        print("\n" + "=" * 70)
        print("Velocity Tracker - Move your hands and controllers")
        print("Press Ctrl+C to exit")
        print("=" * 70 + "\n")
        
        while True:
            result = session.step()
            
            hand_left_vel = result["hand_velocity_left"][0]
            hand_right_vel = result["hand_velocity_right"][0]
            ctrl_left_vel = result["controller_velocity_left"][0]
            ctrl_right_vel = result["controller_velocity_right"][0]
            
            if session.frame_count % 30 == 0:
                elapsed = session.get_elapsed_time()
                print(f"[{elapsed:5.1f}s] Hand L/R: {hand_left_vel:.3f}/{hand_right_vel:.3f} m/s  "
                      f"Ctrl L/R: {ctrl_left_vel:.3f}/{ctrl_right_vel:.3f} m/s")
            
            time.sleep(0.016)  # ~60 FPS
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
