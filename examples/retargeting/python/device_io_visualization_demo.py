#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Comprehensive Device IO Visualization Demo

Demonstrates:
- Reading from device IO (head, hands, controllers)
- Tunable scale parameters for each device
- Real-time 3D visualization showing original and scaled positions
- Graph plotting of tracking quality metrics
- Using TeleopSession for clean setup and management
"""

import sys
import time
import numpy as np
from typing import Dict

from teleopcore.retargeting_engine.interface import (
    BaseRetargeter,
    TensorGroupType,
    TensorGroup,
    Tensor,
    FloatParameter,
    ParameterState,
    VisualizationState,
    RenderSpaceSpec,
    MarkerNodeSpec,
    TextNodeSpec,
    MarkerData,
    TextData,
    GraphSpec,
)
from teleopcore.retargeting_engine.tensor_types import FloatType, HeadPose, HandInput, ControllerInput, NUM_HAND_JOINTS
from teleopcore.retargeting_engine.deviceio_source_nodes import HeadSource, HandsSource, ControllersSource
from teleopcore.teleop_session_manager import TeleopSession, TeleopSessionConfig
from teleopcore.retargeting_engine_ui import MultiRetargeterTuningUIImGui, LayoutModeImGui


def quaternion_to_forward_vector(quat: np.ndarray, default_forward: np.ndarray = np.array([0.0, 0.0, -1.0])) -> np.ndarray:
    """
    Convert quaternion (x, y, z, w) to forward vector by rotating default forward.
    
    Args:
        quat: Quaternion as (x, y, z, w) numpy array
        default_forward: Default forward direction (0, 0, -1) in OpenXR convention
    
    Returns:
        Rotated forward vector as (x, y, z) numpy array
    """
    x, y, z, w = quat[0], quat[1], quat[2], quat[3]
    
    # Rotate default forward vector by quaternion
    # v' = q * v * q^-1
    fx, fy, fz = default_forward[0], default_forward[1], default_forward[2]
    
    # Simplified quaternion rotation formula
    forward = np.array([
        fx*(1 - 2*y*y - 2*z*z) + fy*(2*x*y - 2*w*z) + fz*(2*x*z + 2*w*y),
        fx*(2*x*y + 2*w*z) + fy*(1 - 2*x*x - 2*z*z) + fz*(2*y*z - 2*w*x),
        fx*(2*x*z - 2*w*y) + fy*(2*y*z + 2*w*x) + fz*(1 - 2*x*x - 2*y*y)
    ], dtype=np.float32)
    
    return forward


class DeviceOffsetRetargeter(BaseRetargeter):
    """
    Simple retargeter that applies tunable XYZ offsets to device inputs.
    
    Visualizes both original and offset positions for head, hands, and controllers.
    """
    
    def __init__(self, name: str = "DeviceOffsetRetargeter"):
        # Initialize member variables
        self.time = 0.0
        
        # Original positions and orientations
        self.head_pos = np.array([0.0, 0.0, 0.0])
        self.head_orientation = np.array([0.0, 0.0, 0.0, 1.0])  # Identity quaternion (x,y,z,w)
        self.head_forward = np.array([0.0, 0.0, -1.0])
        
        # Hand joint positions (26 joints per hand) - original from tracking
        self.left_hand_joints = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
        self.right_hand_joints = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
        self.left_hand_pos = np.array([0.0, 0.0, 0.0])  # Wrist position
        self.right_hand_pos = np.array([0.0, 0.0, 0.0])  # Wrist position
        
        # Scaled hand joints (after applying scale parameters)
        self.left_hand_joints_scaled = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
        self.right_hand_joints_scaled = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
        
        # Controller grip poses
        self.left_controller_pos = np.array([0.0, 0.0, 0.0])
        self.right_controller_pos = np.array([0.0, 0.0, 0.0])
        self.left_controller_grip_orientation = np.array([0.0, 0.0, 0.0, 1.0])
        self.right_controller_grip_orientation = np.array([0.0, 0.0, 0.0, 1.0])
        self.left_controller_grip_forward = np.array([0.0, 0.0, -1.0])
        self.right_controller_grip_forward = np.array([0.0, 0.0, -1.0])
        
        # Controller aim poses
        self.left_controller_aim_pos = np.array([0.0, 0.0, 0.0])
        self.right_controller_aim_pos = np.array([0.0, 0.0, 0.0])
        self.left_controller_aim_orientation = np.array([0.0, 0.0, 0.0, 1.0])
        self.right_controller_aim_orientation = np.array([0.0, 0.0, 0.0, 1.0])
        self.left_controller_aim_forward = np.array([0.0, 0.0, -1.0])
        self.right_controller_aim_forward = np.array([0.0, 0.0, -1.0])
        
        # Scaled positions (computed from scale parameters)
        self.left_controller_pos_scaled = np.array([0.0, 0.0, 0.0])
        self.right_controller_pos_scaled = np.array([0.0, 0.0, 0.0])
        self.left_controller_aim_scaled = np.array([0.0, 0.0, 0.0])
        self.right_controller_aim_scaled = np.array([0.0, 0.0, 0.0])
        
        # Scale parameters (set via ParameterState)
        self.hand_size_scale = 1.0  # Scales hand joint positions relative to wrist
        self.hand_distance_scale = 1.0  # Scales hand distance from head
        self.controller_distance_scale = 1.0  # Scales controller distance from head
        
        # Tracking quality metrics
        self.head_quality = 1.0
        self.hands_quality = 1.0
        self.controllers_quality = 1.0
        
        # Previous positions for velocity calculation
        self.prev_head_pos = np.array([0.0, 0.0, 0.0])
        self.prev_left_hand_pos = np.array([0.0, 0.0, 0.0])
        self.prev_right_hand_pos = np.array([0.0, 0.0, 0.0])
        self.prev_left_controller_pos = np.array([0.0, 0.0, 0.0])
        self.prev_right_controller_pos = np.array([0.0, 0.0, 0.0])
        
        # Velocity magnitudes (m/s)
        self.head_velocity = 0.0
        self.left_hand_velocity = 0.0
        self.right_hand_velocity = 0.0
        self.left_controller_velocity = 0.0
        self.right_controller_velocity = 0.0
        
        # Time tracking
        self.time = 0.0
        self.prev_time = 0.0
        
        # Create parameter state with scale parameters
        param_state = ParameterState(
            name=name,
            parameters=[
                FloatParameter(
                    "hand_size_scale", 
                    "Hand Size Scale", 
                    default_value=1.0,
                    min_value=0.5,
                    max_value=4.0,
                    sync_fn=lambda val: setattr(self, 'hand_size_scale', val)
                ),
                FloatParameter(
                    "hand_distance_scale", 
                    "Hand Distance from Head", 
                    default_value=1.0,
                    min_value=0.5,
                    max_value=2.0,
                    sync_fn=lambda val: setattr(self, 'hand_distance_scale', val)
                ),
                FloatParameter(
                    "controller_distance_scale", 
                    "Controller Distance from Head", 
                    default_value=1.0,
                    min_value=0.5,
                    max_value=2.0,
                    sync_fn=lambda val: setattr(self, 'controller_distance_scale', val)
                ),
            ],
            config_file=f"{name.lower().replace(' ', '_')}_config.json"
        )
        
        # Create visualization specs (declared upfront like ParameterState pattern)
        node_specs = []
        graph_specs = []
        
        # Original positions (semi-transparent screen-space markers)
        node_specs.extend([
            MarkerNodeSpec(
                "head_orig",
                initial_data=MarkerData(
                    position=self.head_pos.copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=12.0,
                    color=(0.5, 0.5, 1.0),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.head_pos),
                children=[
                    TextNodeSpec(
                        "head_orig_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.02]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="Head (orig)",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,  # Static text
                    )
                ]
            ),
            MarkerNodeSpec(
                "left_hand_orig",
                initial_data=MarkerData(
                    position=self.left_hand_pos.copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=10.0,
                    color=(0.5, 1.0, 0.5),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.left_hand_pos),
                children=[
                    TextNodeSpec(
                        "left_hand_orig_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.02]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="L Hand (orig)",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,
                    )
                ]
            ),
            MarkerNodeSpec(
                "right_hand_orig",
                initial_data=MarkerData(
                    position=self.right_hand_pos.copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=10.0,
                    color=(1.0, 0.5, 0.5),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.right_hand_pos),
                children=[
                    TextNodeSpec(
                        "right_hand_orig_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.02]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="R Hand (orig)",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,
                    )
                ]
            ),
            MarkerNodeSpec(
                "left_controller_orig",
                initial_data=MarkerData(
                    position=self.left_controller_pos.copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=8.0,
                    color=(0.5, 0.8, 0.5),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.left_controller_pos),
                children=[
                    TextNodeSpec(
                        "left_controller_orig_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.02]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="L Ctrl (orig)",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,
                    )
                ]
            ),
            MarkerNodeSpec(
                "right_controller_orig",
                initial_data=MarkerData(
                    position=self.right_controller_pos.copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=8.0,
                    color=(0.8, 0.5, 0.5),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.right_controller_pos),
                children=[
                    TextNodeSpec(
                        "right_controller_orig_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.02]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="R Ctrl (orig)",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,
                    )
                ]
            )
        ])
        
        # Head position (bright, larger marker)
        node_specs.append(
            MarkerNodeSpec(
                "head",
                initial_data=MarkerData(
                    position=self.head_pos.copy(),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=15.0,
                    color=(0.2, 0.6, 1.0),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.head_pos),
                children=[
                    TextNodeSpec(
                        "head_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.02]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="Head",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,
                    )
                ]
            )
        )
        
        # Scaled hand joints (26 joints per hand) - screen-space markers
        for joint_idx in range(NUM_HAND_JOINTS):
            # Only add label for wrist (joint 0)
            left_children = [
                TextNodeSpec(
                    "left_wrist_label",
                    initial_data=TextData(
                        position=np.array([0.0, 0.0, 0.02]),
                        orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                        visible=True,
                        text="L Wrist",
                        color=(1.0, 1.0, 1.0)
                    ),
                    update_fn=lambda data: None,
                )
            ] if joint_idx == 0 else []
            
            right_children = [
                TextNodeSpec(
                    "right_wrist_label",
                    initial_data=TextData(
                        position=np.array([0.0, 0.0, 0.02]),
                        orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                        visible=True,
                        text="R Wrist",
                        color=(1.0, 1.0, 1.0)
                    ),
                    update_fn=lambda data: None,
                )
            ] if joint_idx == 0 else []
            
            # Capture joint_idx in closure
            node_specs.append(
                MarkerNodeSpec(
                    f"left_hand_joint_{joint_idx}",
                    initial_data=MarkerData(
                        position=np.zeros(3),
                        orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                        visible=True,
                        size=3.0,
                        color=(0.0, 1.0, 0.0),
                    ),
                    update_fn=lambda data, idx=joint_idx: data.position.__setitem__(slice(None), self.left_hand_joints_scaled[idx]),
                    children=left_children
                )
            )
            node_specs.append(
                MarkerNodeSpec(
                    f"right_hand_joint_{joint_idx}",
                    initial_data=MarkerData(
                        position=np.zeros(3),
                        orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                        visible=True,
                        size=3.0,
                        color=(1.0, 0.0, 0.0),
                    ),
                    update_fn=lambda data, idx=joint_idx: data.position.__setitem__(slice(None), self.right_hand_joints_scaled[idx]),
                    children=right_children
                )
            )
        
        # Scaled controller grip poses (screen-space markers)
        node_specs.extend([
            MarkerNodeSpec(
                "left_controller_grip",
                initial_data=MarkerData(
                    position=np.zeros(3),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=11.0,
                    color=(0.0, 0.8, 0.0),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.left_controller_pos_scaled),
                children=[
                    TextNodeSpec(
                        "left_controller_grip_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.02]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="L Grip",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,
                    )
                ]
            ),
            MarkerNodeSpec(
                "right_controller_grip",
                initial_data=MarkerData(
                    position=np.zeros(3),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=11.0,
                    color=(0.8, 0.0, 0.0),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.right_controller_pos_scaled),
                children=[
                    TextNodeSpec(
                        "right_controller_grip_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.02]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="R Grip",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,
                    )
                ]
            )
        ])
        
        # Controller aim poses (fixed offset from grip, doesn't scale with distance)
        node_specs.extend([
            MarkerNodeSpec(
                "left_controller_aim",
                initial_data=MarkerData(
                    position=np.zeros(3),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=9.0,
                    color=(0.0, 1.0, 1.0),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.left_controller_aim_scaled),
                children=[
                    TextNodeSpec(
                        "left_controller_aim_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.015]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="L Aim",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,
                    )
                ]
            ),
            MarkerNodeSpec(
                "right_controller_aim",
                initial_data=MarkerData(
                    position=np.zeros(3),
                    orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                    visible=True,
                    size=9.0,
                    color=(1.0, 1.0, 0.0),
                ),
                update_fn=lambda data: data.position.__setitem__(slice(None), self.right_controller_aim_scaled),
                children=[
                    TextNodeSpec(
                        "right_controller_aim_label",
                        initial_data=TextData(
                            position=np.array([0.0, 0.0, 0.015]),
                            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
                            visible=True,
                            text="R Aim",
                            color=(1.0, 1.0, 1.0)
                        ),
                        update_fn=lambda data: None,
                    )
                ]
            )
        ])
        
        # Graph for head velocity
        graph_specs.append(
            GraphSpec(
                "head_velocity",
                "Head Velocity",
                "Time (s)",
                "Velocity (m/s)",
                sample_fn=lambda: (self.time, self.head_velocity),
                ylim=(0.0, 3.0)
            )
        )
        
        # Create visualization state from specs (matches ParameterState pattern)
        viz_state = VisualizationState(
            name,
            render_space_specs=[
                RenderSpaceSpec("main", "3D View", node_specs=node_specs)
            ],
            graph_specs=graph_specs
        )
        
        # Initialize base with parameter state and visualization state
        super().__init__(name, parameter_state=param_state, visualization_state=viz_state)
        
    def input_spec(self):
        """Declare input tensor groups from device sources."""
        return {
            "head": HeadPose(),
            "hand_left": HandInput(),
            "hand_right": HandInput(),
            "controller_left": ControllerInput(),
            "controller_right": ControllerInput(),
        }
        
    def output_spec(self):
        """Declare output tensor groups with offset positions."""
        return {
            "head_offset": TensorGroupType("head_offset", [
                FloatType("position_x"),
                FloatType("position_y"),
                FloatType("position_z"),
            ]),
            "hands_offset": TensorGroupType("hands_offset", [
                FloatType("left_position_x"),
                FloatType("left_position_y"),
                FloatType("left_position_z"),
                FloatType("right_position_x"),
                FloatType("right_position_y"),
                FloatType("right_position_z"),
            ]),
            "controllers_offset": TensorGroupType("controllers_offset", [
                FloatType("left_position_x"),
                FloatType("left_position_y"),
                FloatType("left_position_z"),
                FloatType("right_position_x"),
                FloatType("right_position_y"),
                FloatType("right_position_z"),
            ]),
        }
        
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Apply offsets to device positions.
        
        Visualization updates automatically via lambdas - no manual updates needed!
        """
        # Update time and calculate dt
        import time as time_module
        current_time = time_module.time()
        dt = current_time - self.prev_time if self.prev_time > 0 else 0.016  # Use actual dt, fallback to 60Hz on first call
        self.prev_time = current_time
        self.time += dt
        
        # Extract head input (HeadPose: position ndarray, orientation, is_valid, timestamp)
        head = inputs["head"]
        head_position = head[0]  # (3,) ndarray
        head_orientation = head[1]  # (4,) ndarray - quaternion (x, y, z, w)
        self.head_pos = np.array([head_position[0], head_position[1], head_position[2]])
        self.head_orientation = head_orientation
        self.head_forward = quaternion_to_forward_vector(self.head_orientation)
        self.head_quality = 1.0 if head[2] else 0.0  # head[2] is is_valid bool
        
        # Extract hands input (separate left/right Hand Input groups)
        # HandInput: joint_positions (26,3), joint_orientations (26,4), joint_radii (26,), joint_valid (26,), is_active, timestamp
        hand_left = inputs["hand_left"]
        hand_right = inputs["hand_right"]
        self.left_hand_joints = hand_left[0]  # (26, 3) ndarray of joint positions
        self.right_hand_joints = hand_right[0]  # (26, 3) ndarray
        # Use wrist position (joint 0)
        self.left_hand_pos = np.array([self.left_hand_joints[0, 0], self.left_hand_joints[0, 1], self.left_hand_joints[0, 2]])
        self.right_hand_pos = np.array([self.right_hand_joints[0, 0], self.right_hand_joints[0, 1], self.right_hand_joints[0, 2]])
        self.hands_quality = 1.0 if (hand_left[4] and hand_right[4]) else 0.0  # both active
        
        # Extract controllers input (separate left/right ControllerInput groups)
        # ControllerInput: grip_position, grip_orientation, aim_position, aim_orientation, buttons, triggers, etc.
        controller_left = inputs["controller_left"]
        controller_right = inputs["controller_right"]
        
        # Grip poses
        left_grip_pos = controller_left[0]  # (3,) ndarray
        left_grip_ori = controller_left[1]  # (4,) ndarray - quaternion (x, y, z, w)
        right_grip_pos = controller_right[0]  # (3,) ndarray
        right_grip_ori = controller_right[1]  # (4,) ndarray
        self.left_controller_pos = np.array([left_grip_pos[0], left_grip_pos[1], left_grip_pos[2]])
        self.right_controller_pos = np.array([right_grip_pos[0], right_grip_pos[1], right_grip_pos[2]])
        self.left_controller_grip_orientation = left_grip_ori
        self.right_controller_grip_orientation = right_grip_ori
        self.left_controller_grip_forward = quaternion_to_forward_vector(self.left_controller_grip_orientation)
        self.right_controller_grip_forward = quaternion_to_forward_vector(self.right_controller_grip_orientation)
        
        # Aim poses
        left_aim_pos = controller_left[2]  # (3,) ndarray
        left_aim_ori = controller_left[3]  # (4,) ndarray
        right_aim_pos = controller_right[2]  # (3,) ndarray
        right_aim_ori = controller_right[3]  # (4,) ndarray
        self.left_controller_aim_pos = np.array([left_aim_pos[0], left_aim_pos[1], left_aim_pos[2]])
        self.right_controller_aim_pos = np.array([right_aim_pos[0], right_aim_pos[1], right_aim_pos[2]])
        self.left_controller_aim_orientation = left_aim_ori
        self.right_controller_aim_orientation = right_aim_ori
        self.left_controller_aim_forward = quaternion_to_forward_vector(self.left_controller_aim_orientation)
        self.right_controller_aim_forward = quaternion_to_forward_vector(self.right_controller_aim_orientation)
        
        self.controllers_quality = 1.0  # Controllers don't have quality in standard type
        
        # Apply scale parameters (all scales are relative to head position)
        # Hand size scale: scale each joint position relative to wrist
        # Hand distance scale: scale wrist position relative to head
        for i in range(NUM_HAND_JOINTS):
            # Get joint offset from wrist
            left_joint_offset = self.left_hand_joints[i] - self.left_hand_pos
            right_joint_offset = self.right_hand_joints[i] - self.right_hand_pos
            
            # Scale joint offset by hand_size_scale
            left_joint_offset_scaled = left_joint_offset * self.hand_size_scale
            right_joint_offset_scaled = right_joint_offset * self.hand_size_scale
            
            # Get wrist offset from head and scale by hand_distance_scale
            left_wrist_offset = self.left_hand_pos - self.head_pos
            right_wrist_offset = self.right_hand_pos - self.head_pos
            left_wrist_scaled = self.head_pos + left_wrist_offset * self.hand_distance_scale
            right_wrist_scaled = self.head_pos + right_wrist_offset * self.hand_distance_scale
            
            # Final scaled joint position
            self.left_hand_joints_scaled[i] = left_wrist_scaled + left_joint_offset_scaled
            self.right_hand_joints_scaled[i] = right_wrist_scaled + right_joint_offset_scaled
        
        # Controller distance scale: scale GRIP position relative to head
        # Keep aim offset from grip UNCHANGED (don't scale the gap)
        left_controller_offset = self.left_controller_pos - self.head_pos
        right_controller_offset = self.right_controller_pos - self.head_pos
        self.left_controller_pos_scaled = self.head_pos + left_controller_offset * self.controller_distance_scale
        self.right_controller_pos_scaled = self.head_pos + right_controller_offset * self.controller_distance_scale
        
        # Aim stays at fixed offset from scaled grip (gap doesn't change with distance)
        left_aim_offset_from_grip = self.left_controller_aim_pos - self.left_controller_pos
        right_aim_offset_from_grip = self.right_controller_aim_pos - self.right_controller_pos
        self.left_controller_aim_scaled = self.left_controller_pos_scaled + left_aim_offset_from_grip
        self.right_controller_aim_scaled = self.right_controller_pos_scaled + right_aim_offset_from_grip
        
        # Calculate velocities (magnitude in m/s) using actual dt
        self.head_velocity = np.linalg.norm(self.head_pos - self.prev_head_pos) / dt if dt > 0 else 0.0
        self.left_hand_velocity = np.linalg.norm(self.left_hand_pos - self.prev_left_hand_pos) / dt if dt > 0 else 0.0
        self.right_hand_velocity = np.linalg.norm(self.right_hand_pos - self.prev_right_hand_pos) / dt if dt > 0 else 0.0
        self.left_controller_velocity = np.linalg.norm(self.left_controller_pos - self.prev_left_controller_pos) / dt if dt > 0 else 0.0
        self.right_controller_velocity = np.linalg.norm(self.right_controller_pos - self.prev_right_controller_pos) / dt if dt > 0 else 0.0
        
        # Update previous positions for next frame
        self.prev_head_pos = self.head_pos.copy()
        self.prev_left_hand_pos = self.left_hand_pos.copy()
        self.prev_right_hand_pos = self.right_hand_pos.copy()
        self.prev_left_controller_pos = self.left_controller_pos.copy()
        self.prev_right_controller_pos = self.right_controller_pos.copy()
        
        # That's it! Visualization pulls from member vars via lambdas
        
        # Set outputs using integer indices (matching tensor order in output_spec)
        # Head position (3 floats: x, y, z)
        outputs["head_offset"][0] = float(self.head_pos[0])
        outputs["head_offset"][1] = float(self.head_pos[1])
        outputs["head_offset"][2] = float(self.head_pos[2])
        
        # Scaled hand wrist positions (6 floats: left x,y,z, right x,y,z)
        outputs["hands_offset"][0] = float(self.left_hand_joints_scaled[0, 0])
        outputs["hands_offset"][1] = float(self.left_hand_joints_scaled[0, 1])
        outputs["hands_offset"][2] = float(self.left_hand_joints_scaled[0, 2])
        outputs["hands_offset"][3] = float(self.right_hand_joints_scaled[0, 0])
        outputs["hands_offset"][4] = float(self.right_hand_joints_scaled[0, 1])
        outputs["hands_offset"][5] = float(self.right_hand_joints_scaled[0, 2])
        
        # Scaled controller positions (6 floats: left x,y,z, right x,y,z)
        outputs["controllers_offset"][0] = float(self.left_controller_pos_scaled[0])
        outputs["controllers_offset"][1] = float(self.left_controller_pos_scaled[1])
        outputs["controllers_offset"][2] = float(self.left_controller_pos_scaled[2])
        outputs["controllers_offset"][3] = float(self.right_controller_pos_scaled[0])
        outputs["controllers_offset"][4] = float(self.right_controller_pos_scaled[1])
        outputs["controllers_offset"][5] = float(self.right_controller_pos_scaled[2])


def main():
    """Run comprehensive device IO visualization demo using TeleopSession."""
    print("\n" + "=" * 70)
    print("Device IO Visualization Demo (TeleopSession)")
    print("=" * 70)
    print("\nThis demo shows:")
    print("  - Head, hands, and controllers from DeviceIO")
    print("  - Tunable scale parameters for each device")
    print("  - 3D visualization of original (faded) and scaled (bright) positions")
    print("  - Real-time graphs of tracking quality")
    print("  - Clean setup using TeleopSession")
    
    # ========================================================================
    # Step 1: Create DeviceIO sources (they create their own trackers)
    # ========================================================================
    print("\n[1/4] Creating source modules...")
    head_source = HeadSource(name="head")
    hands_source = HandsSource(name="hands")
    controllers_source = ControllersSource(name="controllers")
    print(f"  ✓ Created HeadSource (auto-creates HeadTracker)")
    print(f"  ✓ Created HandsSource (auto-creates HandTracker)")
    print(f"  ✓ Created ControllersSource (auto-creates ControllerTracker)")
    
    # ========================================================================
    # Step 2: Create visualization retargeter and connect to sources
    # ========================================================================
    print("\n[2/4] Creating visualization retargeter...")
    retargeter = DeviceOffsetRetargeter("DeviceOffsetRetargeter")
    print("  ✓ Retargeter created with spec-based visualization")
    
    # Connect retargeter to source outputs
    print("\n[3/4] Building retargeting pipeline...")
    pipeline = retargeter.connect({
        "head": head_source.output("head"),
        "hand_left": hands_source.output("hand_left"),
        "hand_right": hands_source.output("hand_right"),
        "controller_left": controllers_source.output("controller_left"),
        "controller_right": controllers_source.output("controller_right"),
    })
    print("  ✓ Pipeline built (sources → retargeter)")
    print("  ✓ Trackers will be auto-discovered from sources!")
    
    # ========================================================================
    # Step 3: Create TeleopSession config
    # ========================================================================
    print("\n[4/4] Configuring TeleopSession...")
    config = TeleopSessionConfig(
        app_name="DeviceIOVisualizationDemo",
        pipeline=pipeline,
        verbose=True
    )
    print("  ✓ Config created")
    
    # ========================================================================
    # Run TeleopSession with manual UI management
    # ========================================================================
    print("\n" + "=" * 70)
    print("Starting TeleopSession and UI...")
    print("=" * 70)
    
    with TeleopSession(config) as session:
        print("\n✅ Session started successfully!")
        
        # Create UI manually
        with MultiRetargeterTuningUIImGui(
            [retargeter],
            title="Device I/O Visualization & Parameters",
            layout_mode=LayoutModeImGui.HORIZONTAL
        ) as ui:
            print("✅ UI started")
            print("\nRunning main loop...")
            print("  - TeleopSession polls DeviceIO trackers automatically")
            print("  - Pipeline executes: sources → retargeter → visualization")
            print("  - Tune scale parameters in real-time!")
            print("  - Close window or press Ctrl+C to exit\n")
            
            frame = 0
            start_time = time.time()
            
            try:
                while ui.is_running():
                    # Run one iteration - handles DeviceIO update and pipeline execution
                    outputs = session.step()
                    
                    # Progress every 3 seconds
                    if frame % 180 == 0 and frame > 0:
                        elapsed = time.time() - start_time
                        fps = frame / elapsed if elapsed > 0 else 0
                        
                        # Read outputs from the pipeline
                        head_x = outputs["head_offset"][0]
                        head_y = outputs["head_offset"][1]
                        head_z = outputs["head_offset"][2]
                        
                        print(f"  [{elapsed:.1f}s] Frame {frame} - FPS: {fps:.1f} - "
                              f"Head: [{head_x:.3f}, {head_y:.3f}, {head_z:.3f}] - "
                              f"Scales: hand_size={retargeter.hand_size_scale:.2f}, "
                              f"hand_dist={retargeter.hand_distance_scale:.2f}, "
                              f"ctrl_dist={retargeter.controller_distance_scale:.2f}")
                    
                    frame += 1
                    time.sleep(0.016)  # 60 Hz
                    
            except KeyboardInterrupt:
                print("\n  Interrupted by user")
            
            elapsed = time.time() - start_time
            fps = frame / elapsed if elapsed > 0 else 0
            print(f"\n✓ Demo complete ({elapsed:.1f}s, {frame} frames, {fps:.1f} FPS)")
    
    print("\n✅ Demo completed successfully!")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

