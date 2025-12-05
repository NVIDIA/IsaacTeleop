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
    from teleopcore.retargeting_engine.sources import ControllersSource
    from teleopcore.retargeting_engine.examples import GripperRetargeter
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore is built and installed")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def main():
    # Create controller tracker
    controller_tracker = deviceio.ControllerTracker()
    
    # Create controllers source
    controllers = ControllersSource(controller_tracker, name="controllers")
    
    # Build retargeting graph using new API
    gripper = GripperRetargeter(name="gripper")
    connected = gripper.connect({
        "controller_left": controllers.output("controller_left"),
        "controller_right": controllers.output("controller_right")
    })
    
    # Get required extensions and create OpenXR session
    trackers = [controller_tracker]
    required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
    
    with oxr.OpenXRSession.create("GripperRetargetingExample", required_extensions) as oxr_session:
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
                    run_loop(deviceio_session, connected)
            else:
                run_loop(deviceio_session, connected)
    
    return 0


def run_loop(deviceio_session, connected_module):
    """Run the control loop."""
    start_time = time.time()
    frame_count = 0
    
    print("Starting gripper retargeting (20 seconds)...")
    print("=" * 60)
    
    while time.time() - start_time < 20.0:
        # Update DeviceIO session (polls trackers)
        deviceio_session.update()
        
        # Execute retargeting graph - returns Dict[str, TensorGroup]
        result = connected_module()
        
        # Access output values
        left_gripper = result["gripper_left"][0]
        right_gripper = result["gripper_right"][0]
        
        # Print every 0.5 seconds
        if frame_count % 30 == 0:
            elapsed = time.time() - start_time
            print(f"[{elapsed:5.1f}s] Left: {left_gripper:.2f}  Right: {right_gripper:.2f}")
        
        frame_count += 1
        time.sleep(0.016)  # ~60 FPS
    
    print("=" * 60)
    print(f"Completed {frame_count} frames in {time.time() - start_time:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
