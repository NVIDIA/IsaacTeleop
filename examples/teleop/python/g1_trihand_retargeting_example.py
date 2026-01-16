#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
G1 TriHand Retargeting Example

Demonstrates using the TriHandMotionController module to retarget motion controller
inputs to G1 robot hand joints.

This example shows:
1. TriHandMotionController - Simple VR controller-based hand control for G1 TriHand
"""

import sys
import time
from pathlib import Path

try:
    import teleopcore.deviceio as deviceio
    import teleopcore.oxr as oxr
    import teleopcore.plugin_manager as pm
    from teleopcore.retargeting_engine.sources import ControllersSource
    from teleopcore.retargeting_engine.retargeters import (
        TriHandMotionController,
        TriHandMotionControllerConfig,
    )
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore is built and installed")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def example_trihand_motion_controller():
    """Run TriHandMotionController example with VR controllers."""
    print("\n" + "=" * 80)
    print("  TriHandMotionController Example")
    print("=" * 80)
    print("\nMapping VR controller inputs to G1 TriHand joints...")
    print("- Trigger: Controls index finger")
    print("- Squeeze: Controls middle finger")
    print("- Both: Controls thumb\n")

    # Create controller tracker
    controller_tracker = deviceio.ControllerTracker()

    # Create controllers source
    controllers = ControllersSource(controller_tracker, name="controllers")

    # Configure TriHandMotionController for G1 7-DOF hand
    hand_joint_names = [
        "thumb_rotation",
        "thumb_proximal",
        "thumb_distal",
        "index_proximal",
        "index_distal",
        "middle_proximal",
        "middle_distal",
    ]

    # Create left hand controller
    left_config = TriHandMotionControllerConfig(
        hand_joint_names=hand_joint_names,
        controller_side="left",
    )
    left_controller = TriHandMotionController(left_config, name="trihand_motion_left")

    # Connect left controller to source
    connected_left = left_controller.connect({
        "controller_left": controllers.output("controller_left")
    })

    # Create right hand controller
    right_config = TriHandMotionControllerConfig(
        hand_joint_names=hand_joint_names,
        controller_side="right",
    )
    right_controller = TriHandMotionController(right_config, name="trihand_motion_right")

    # Connect right controller to source
    connected_right = right_controller.connect({
        "controller_right": controllers.output("controller_right")
    })

    # Get required extensions and create OpenXR session
    trackers = [controller_tracker]
    required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)

    with oxr.OpenXRSession.create("TriHandMotionControllerExample", required_extensions) as oxr_session:
        handles = oxr_session.get_handles()

        # Create DeviceIO session with trackers
        with deviceio.DeviceIOSession.run(trackers, handles) as deviceio_session:
            # Initialize plugin (if available)
            plugin_context = None
            if PLUGIN_ROOT_DIR.exists():
                manager = pm.PluginManager([str(PLUGIN_ROOT_DIR)])
                if PLUGIN_NAME in manager.get_plugin_names():
                    plugin_context = manager.start(PLUGIN_NAME, PLUGIN_ROOT_ID)

            # Run control loop
            if plugin_context:
                with plugin_context:
                    run_motion_controller_loop(deviceio_session, connected_left, connected_right)
            else:
                run_motion_controller_loop(deviceio_session, connected_left, connected_right)

    return 0


def run_motion_controller_loop(deviceio_session, connected_left, connected_right):
    """Run the motion controller loop."""
    start_time = time.time()
    frame_count = 0

    print("Running for 20 seconds...")
    print("=" * 80)

    while time.time() - start_time < 20.0:
        # Update DeviceIO session (polls trackers)
        deviceio_session.update()

        # Execute retargeting graph for both hands
        result_left = connected_left()
        result_right = connected_right()

        # Access output joint angles
        joints_left = result_left["hand_joints"]
        joints_right = result_right["hand_joints"]

        # Print every 0.5 seconds
        if frame_count % 30 == 0:
            elapsed = time.time() - start_time

            # Left hand (thumb, index, middle)
            l_thumb = joints_left[0]
            l_index = joints_left[3]
            l_middle = joints_left[5]

            # Right hand (thumb, index, middle)
            r_thumb = joints_right[0]
            r_index = joints_right[3]
            r_middle = joints_right[5]

            print(f"[{elapsed:5.1f}s] L: T={l_thumb:5.2f} I={l_index:5.2f} M={l_middle:5.2f} | R: T={r_thumb:5.2f} I={r_index:5.2f} M={r_middle:5.2f}")

        frame_count += 1
        time.sleep(0.016)  # ~60 FPS

    print("=" * 80)
    print(f"✓ Completed {frame_count} frames in {time.time() - start_time:.1f}s")


def main():
    """Main entry point."""
    return example_trihand_motion_controller()


if __name__ == "__main__":
    sys.exit(main())

