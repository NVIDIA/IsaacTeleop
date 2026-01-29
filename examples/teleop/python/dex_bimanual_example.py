#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Dex BiManual Retargeting Example

Demonstrates using DexBiManualRetargeter to control two hands simultaneously.
"""

import sys
import time
from pathlib import Path

import teleopcore.deviceio as deviceio
import teleopcore.oxr as oxr
from teleopcore.retargeting_engine.deviceio_source_nodes import HandsSource
from teleopcore.retargeting_engine.retargeters import (
    DexBiManualRetargeter,
    DexHandRetargeterConfig
)
from teleopcore.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig
)


def main():
    print("\n" + "=" * 80)
    print("  Dex BiManual Retargeting Example")
    print("=" * 80)
    print("Requires dex-retargeting library and config files.")
    print("This example assumes a robot with both left and right hands.")
    print("=" * 80 + "\n")

    # Check for config files
    # Note: These paths are placeholders. In a real scenario, you'd point to your robot's config.
    # We'll use the example configs from dex_hand_retargeting_example.py logic if they existed,
    # but since this is an example, we'll mock the paths or expect them relative to this script.

    # We'll assume the user has set up the configs similar to the single hand example
    config_dir = Path(__file__).parent / "config" / "dex_retargeting"
    left_yaml = config_dir / "hand_left_config.yml"
    right_yaml = config_dir / "hand_right_config.yml"
    left_urdf_path = config_dir / "left_robot_hand.urdf" # Assuming same URDF or distinct ones
    right_urdf_path = config_dir / "right_robot_hand.urdf"
    # Check if files exist (soft check)
    if not left_yaml.exists():
        print(f"Warning: Config file {left_yaml} not found. Example may fail.")

    # ==================================================================
    # Build Retargeting Pipeline
    # ==================================================================

    # Create source (tracker is internal)
    hands = HandsSource(name="hands")

    # Dummy joint names for example
    left_joints = [
        "L_thumb_proximal_yaw_joint", "L_thumb_proximal_pitch_joint",
        "L_index_proximal_joint", "L_index_distal_joint",
        "L_middle_proximal_joint", "L_middle_distal_joint",
        "L_ring_proximal_joint", "L_ring_distal_joint",
        "L_pinky_proximal_joint", "L_pinky_distal_joint"
    ]
    right_joints = [
        "R_thumb_proximal_yaw_joint", "R_thumb_proximal_pitch_joint",
        "R_index_proximal_joint", "R_index_distal_joint",
        "R_middle_proximal_joint", "R_middle_distal_joint",
        "R_ring_proximal_joint", "R_ring_distal_joint",
        "R_pinky_proximal_joint", "R_pinky_distal_joint"
    ]
    target_joints = left_joints + right_joints

    # Left Config
    left_cfg = DexHandRetargeterConfig(
        hand_joint_names=left_joints,
        hand_retargeting_config=str(left_yaml),
        hand_urdf=str(left_urdf_path),
        hand_side="left",
    )

    # Right Config
    right_cfg = DexHandRetargeterConfig(
        hand_joint_names=right_joints,
        hand_retargeting_config=str(right_yaml),
        hand_urdf=str(right_urdf_path),
        hand_side="right",
    )

    bimanual = DexBiManualRetargeter(
        left_config=left_cfg,
        right_config=right_cfg,
        target_joint_names=target_joints,
        name="bimanual_hands"
    )

    pipeline = bimanual.connect({
        HandsSource.LEFT: hands.output(HandsSource.LEFT),
        HandsSource.RIGHT: hands.output(HandsSource.RIGHT),
    })

    # ==================================================================
    # Create and run TeleopSession
    # ==================================================================

    session_config = TeleopSessionConfig(
        app_name="DexBiManualExample",
        trackers=[], # Auto-discovered from pipeline
        pipeline=pipeline,
    )

    with TeleopSession(session_config) as session:
        start_time = time.time()

        while time.time() - start_time < 20.0:
            result = session.step()

            # Output: Combined joint angles
            # result["hand_joints"] is a TensorGroup containing scalar floats
            joints = list(result["hand_joints"])

            if session.frame_count % 30 == 0:
                elapsed = session.get_elapsed_time()
                # Print first few joints from left and right parts
                n_left = len(left_joints)
                l_vals = joints[:min(3, n_left)]
                r_vals = joints[n_left:n_left+min(3, len(right_joints))]

                print(f"[{elapsed:5.1f}s] L: {l_vals} ... R: {r_vals} ...")

            time.sleep(0.016)


    return 0


if __name__ == "__main__":
    sys.exit(main())
