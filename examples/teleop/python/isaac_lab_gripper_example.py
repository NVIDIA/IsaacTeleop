#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
IsaacLab Gripper Retargeting Example

Demonstrates using the Pinch-based GripperRetargeter (ported from IsaacLab).
Uses hand tracking (thumb-index distance) to control gripper state.
"""

import sys
import time
from pathlib import Path
import teleopcore.deviceio as deviceio

try:
    from teleopcore.retargeting_engine.retargeters import (
        GripperRetargeter,
        GripperRetargeterConfig,
    )
    from teleopcore.teleop_session_manager import TeleopSession, TeleopSessionConfig, create_standard_inputs
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore and all modules are built and installed")
    sys.exit(1)


def main():
    print("\n" + "=" * 80)
    print("  Pinch Gripper Retargeting (Right Hand)")
    print("=" * 80)
    print("Controls:")
    print("  Pinch Thumb & Index : Close Gripper")
    print("  Open Fingers        : Open Gripper")
    print("=" * 80 + "\n")

    # ==================================================================
    # Setup: Create standard inputs (trackers + sources)
    # ==================================================================

    hand_tracker = deviceio.HandTracker()
    controller_tracker = deviceio.ControllerTracker()
    trackers = [hand_tracker, controller_tracker]
    sources = create_standard_inputs(trackers)
    hands = sources["hands"]
    controllers = sources["controllers"]

    # ==================================================================
    # Build Retargeting Pipeline
    # ==================================================================

    config = GripperRetargeterConfig(
        hand_side="right",
        gripper_close_meters=0.03, # 3cm
        gripper_open_meters=0.05,  # 5cm (hysteresis)
    )

    gripper = GripperRetargeter(config, name="gripper")

    pipeline = gripper.connect({
        "hand_right": hands.output("hand_right"),
        "controller_right": controllers.output("controller_right"),
    })

    # ==================================================================
    # Create and run TeleopSession
    # ==================================================================

    session_config = TeleopSessionConfig(
        app_name="IsaacLabGripperExample",
        trackers=[], # Empty list if using new sources
        pipeline=pipeline,
    )

    with TeleopSession(session_config) as session:
        # No session injection needed

        start_time = time.time()

        try:
            while time.time() - start_time < 30.0:
                result = session.step()

                # Output: -1.0 (closed) or 1.0 (open)
                cmd = result["gripper_command"][0]
                state = "CLOSED" if cmd < 0 else "OPEN"

                # Print status every 0.2 seconds
                if session.frame_count % 12 == 0:
                    elapsed = session.get_elapsed_time()
                    print(f"[{elapsed:5.1f}s] Gripper Command: {cmd:.1f} ({state})")

                time.sleep(0.016)

            print("\nTime limit reached.")

        except KeyboardInterrupt:
            print("\n\nInterrupted by user")

    return 0


if __name__ == "__main__":
    sys.exit(main())
