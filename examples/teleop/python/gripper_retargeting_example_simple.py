#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Simplified Gripper Retargeting Example

Demonstrates using TeleopSession with the new retargeting engine.
Minimal boilerplate - just configure and run!
"""

import sys
import time
from pathlib import Path

try:
    import teleopcore.deviceio as deviceio
    import teleopcore.oxr as oxr
    from teleopcore.retargeting_engine.sources import ControllersSource
    from teleopcore.retargeting_engine.examples import GripperRetargeter
    from teleopcore.teleop_utils import TeleopSession, TeleopSessionConfig, PluginConfig
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore and all modules are built and installed")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def main():
    # ==================================================================
    # Setup: Create trackers
    # ==================================================================
    
    controller_tracker = deviceio.ControllerTracker()
    
    # ==================================================================
    # Build Retargeting Pipeline
    # ==================================================================
    
    controllers = ControllersSource(controller_tracker, name="controllers")
    gripper = GripperRetargeter(name="gripper")
    pipeline = gripper.connect({
        "controller_left": controllers.output("controller_left"),
        "controller_right": controllers.output("controller_right")
    })
    
    # ==================================================================
    # Configure Plugins (optional)
    # ==================================================================
    
    plugins = []
    if PLUGIN_ROOT_DIR.exists():
        plugins.append(PluginConfig(
            plugin_name=PLUGIN_NAME,
            plugin_root_id=PLUGIN_ROOT_ID,
            search_paths=[PLUGIN_ROOT_DIR],
        ))
    
    # ==================================================================
    # Create and run TeleopSession
    # ==================================================================
    
    config = TeleopSessionConfig(
        app_name="GripperRetargetingSimple",
        trackers=[controller_tracker],
        pipeline=pipeline,
        plugins=plugins,
    )
    
    with TeleopSession(config) as session:
        print("\n" + "=" * 60)
        print("Gripper Retargeting - Squeeze triggers to control grippers")
        print("=" * 60 + "\n")
        
        start_time = time.time()
        
        try:
            while time.time() - start_time < 20.0:
                # Run one iteration (updates trackers + executes pipeline)
                result = session.run()
                
                # Get gripper values
                left = result["gripper_left"][0]
                right = result["gripper_right"][0]
                
                # Print status every 0.5 seconds
                if session.frame_count % 30 == 0:
                    elapsed = session.get_elapsed_time()
                    print(f"[{elapsed:5.1f}s] Left: {left:.2f}  Right: {right:.2f}")
                
                time.sleep(0.016)  # ~60 FPS
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

