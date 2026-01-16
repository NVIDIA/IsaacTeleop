#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SE3 Retargeting Example

Demonstrates using Se3AbsRetargeter and Se3RelRetargeter to generate end-effector
poses from hand tracking data.
"""

import sys
import time
import numpy as np
from pathlib import Path

try:
    import teleopcore.deviceio as deviceio
    from teleopcore.retargeting_engine.sources import HandsSource
    from teleopcore.retargeting_engine.retargeters import (
        Se3AbsRetargeter,
        Se3RelRetargeter,
        Se3RetargeterConfig,
    )
    from teleopcore.teleop_utils import TeleopSession, TeleopSessionConfig
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore and all modules are built and installed")
    sys.exit(1)


def run_abs_example():
    print("\n" + "=" * 80)
    print("  SE3 Absolute Retargeting (Right Hand)")
    print("=" * 80)
    print("Maps hand pose directly to End-Effector pose.")
    print("Using 'pinch' center (midpoint of thumb/index) for position.")
    print("=" * 80 + "\n")

    hand_tracker = deviceio.HandTracker()
    hands = HandsSource(hand_tracker, name="hands")

    config = Se3RetargeterConfig(
        input_device="hand_right",
        use_wrist_position=False,
        zero_out_xy_rotation=False,
    )

    retargeter = Se3AbsRetargeter(config, name="se3_abs")

    pipeline = retargeter.connect({
        "hand_right": hands.output("hand_right")
    })

    session_config = TeleopSessionConfig(
        app_name="Se3AbsExample",
        trackers=[hand_tracker],
        pipeline=pipeline,
    )

    with TeleopSession(session_config) as session:
        start_time = time.time()
        try:
            while time.time() - start_time < 20.0:
                result = session.run()

                # Output: [x, y, z, qx, qy, qz, qw]
                pose = result["ee_pose"][0]
                pos = pose[:3]
                rot = pose[3:] # w,x,y,z

                if session.frame_count % 30 == 0:
                    elapsed = session.get_elapsed_time()
                    print(f"[{elapsed:5.1f}s] Pos: ({pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f})  Rot: ({rot[0]:.2f}, {rot[1]:.2f}, {rot[2]:.2f}, {rot[3]:.2f})")

                time.sleep(0.016)
        except KeyboardInterrupt:
            pass


def run_rel_example():
    print("\n" + "=" * 80)
    print("  SE3 Relative Retargeting (Right Hand)")
    print("=" * 80)
    print("Maps hand movement DELTAS to End-Effector deltas.")
    print("Move your hand to generate velocity commands.")
    print("=" * 80 + "\n")

    hand_tracker = deviceio.HandTracker()
    hands = HandsSource(hand_tracker, name="hands")

    config = Se3RetargeterConfig(
        input_device="hand_right",
        use_wrist_position=False,
        zero_out_xy_rotation=True,
        delta_pos_scale_factor=5.0,
        delta_rot_scale_factor=2.0,
    )

    retargeter = Se3RelRetargeter(config, name="se3_rel")

    pipeline = retargeter.connect({
        "hand_right": hands.output("hand_right")
    })

    session_config = TeleopSessionConfig(
        app_name="Se3RelExample",
        trackers=[hand_tracker],
        pipeline=pipeline,
    )

    with TeleopSession(session_config) as session:
        start_time = time.time()
        try:
            while time.time() - start_time < 20.0:
                result = session.run()

                # Output: [dx, dy, dz, drx, dry, drz]
                delta = result["ee_delta"][0]
                dpos = delta[:3]
                drot = delta[3:]

                if session.frame_count % 30 == 0:
                    elapsed = session.get_elapsed_time()
                    # Calculate magnitude for easier reading
                    vel_mag = np.linalg.norm(dpos)
                    rot_mag = np.linalg.norm(drot)
                    print(f"[{elapsed:5.1f}s] Vel Mag: {vel_mag:.4f}  Rot Mag: {rot_mag:.4f} | dPos: ({dpos[0]:.3f}, ...)")

                time.sleep(0.016)
        except KeyboardInterrupt:
            pass


def main():
    print("=" * 80)
    print("  SE3 Retargeting Examples")
    print("=" * 80)
    print("1. Absolute Positioning (Pose -> Pose)")
    print("2. Relative Positioning (Delta -> Delta)")

    choice = input("\nEnter choice (1-2): ").strip()

    if choice == "1":
        run_abs_example()
    elif choice == "2":
        run_rel_example()
    else:
        print("Invalid choice")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

