#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Complete Gripper Retargeting Example

Demonstrates manual setup without TeleopSession for full control.
Shows all the steps that TeleopSession automates.
"""

import sys
import time
from pathlib import Path

try:
    import teleopcore.xrio as xrio
    import teleopcore.oxr as oxr
    import teleopcore.plugin_manager as pm
    from teleopcore.retargeting_engine import RetargeterExecutor, GripperRetargeter
    from teleopcore.retargeting_engine.xrio import ControllersInput
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore is built and installed")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def main():
    # Create XRIO session builder
    builder = xrio.XrioSessionBuilder()
    
    # Create XRIO update node (will create OpenXR and XRIO sessions lazily)
    from teleopcore.retargeting_engine.xrio import XrioUpdateNode
    xrio_update = XrioUpdateNode(builder, app_name="GripperRetargetingExample")
    
    # Create input nodes (they register trackers with builder)
    controllers = ControllersInput(builder)
    controllers.connect_trigger(xrio_update.trigger())
    
    # Build retargeting graph
    gripper = GripperRetargeter(name="gripper")
    gripper.connect_controllers(controllers.left(), controllers.right())
    executor = RetargeterExecutor([gripper])
    
    # Initialize plugin (if available)
    plugin_context = None
    if PLUGIN_ROOT_DIR.exists():
        manager = pm.PluginManager([str(PLUGIN_ROOT_DIR)])
        if PLUGIN_NAME in manager.get_plugin_names():
            plugin_context = manager.start(PLUGIN_NAME, PLUGIN_ROOT_ID)
    
    # Run control loop - sessions build on first execute(), cleanup in destructor
    if plugin_context:
        with plugin_context:
            run_loop(executor)
    else:
        run_loop(executor)
    
    return 0


def run_loop(executor):
    """Run the control loop."""
    start_time = time.time()
    frame_count = 0
    
    while time.time() - start_time < 20.0:
        # Execute the graph (xrio_update will build and update session on first call)
        executor.execute()
        
        # Get outputs
        result = executor.get_output_results()
        left_gripper = result[0][0][0]
        right_gripper = result[0][1][0]
        
        # Print every 0.5 seconds
        if frame_count % 30 == 0:
            elapsed = time.time() - start_time
            print(f"[{elapsed:5.1f}s] Left: {left_gripper:.2f}  Right: {right_gripper:.2f}")
        
        frame_count += 1
        time.sleep(0.016)  # ~60 FPS


if __name__ == "__main__":
    sys.exit(main())
