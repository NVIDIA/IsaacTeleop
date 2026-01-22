#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Complete Gripper Retargeting Example

Demonstrates using the new retargeting engine with direct module composition.
Shows manual setup without helper utilities for full control.
"""

import sys
import time
from pathlib import Path

try:
    import teleopcore.deviceio as deviceio
    import teleopcore.oxr as oxr
    import teleopcore.plugin_manager as pm
    from teleopcore.retargeting_engine.deviceio_source_nodes import ControllersSource
    from teleopcore.retargeting_engine.retargeters import GripperRetargeter
    # Import TeleopSession to handle the loop correctly with new sources
    from teleopcore.teleop_session_manager import TeleopSession, TeleopSessionConfig, PluginConfig
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore is built and installed")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def main():
    # Create controllers source (tracker is internal)
    controllers = ControllersSource(name="controllers")

    # Build retargeting graph using new API
    gripper = GripperRetargeter(name="gripper")
    connected = gripper.connect({
        "controller_left": controllers.output("controller_left"),
        "controller_right": controllers.output("controller_right")
    })

    # Configure Plugins
    plugins = []
    if PLUGIN_ROOT_DIR.exists():
        plugins.append(PluginConfig(
            plugin_name=PLUGIN_NAME,
            plugin_root_id=PLUGIN_ROOT_ID,
            search_paths=[PLUGIN_ROOT_DIR],
        ))

    # Create TeleopSessionConfig
    config = TeleopSessionConfig(
        app_name="GripperRetargetingExample",
        trackers=[], # Auto-discovered
        pipeline=connected,
        plugins=plugins
    )

    # Use TeleopSession to manage the loop and data injection
    with TeleopSession(config) as session:
        run_loop(session)

    return 0


def run_loop(session):
    """Run the control loop using TeleopSession."""
    start_time = time.time()

    print("Starting gripper retargeting (20 seconds)...")
    print("=" * 60)

    while time.time() - start_time < 20.0:
        # Execute retargeting graph via session
                result = session.step()

        # Access output values
        left_gripper = result["gripper_left"][0]
        right_gripper = result["gripper_right"][0]

        # Print every 0.5 seconds
        if session.frame_count % 30 == 0:
            elapsed = session.get_elapsed_time()
            print(f"[{elapsed:5.1f}s] Left: {left_gripper:.2f}  Right: {right_gripper:.2f}")

        time.sleep(0.016)  # ~60 FPS

    print("=" * 60)
    print(f"Completed {session.frame_count} frames in {time.time() - start_time:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
