#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Gripper Retargeting Example with External OpenXR Session

Demonstrates using the retargeting engine with an externally managed OpenXR session.
This is useful when you need custom OpenXR extensions or want full control over
the OpenXR session lifecycle.

The key difference from the simple example:
- You create and manage the OpenXR session
- You get required extensions from the XrioSessionBuilder
- You pass the OpenXR handles to XrioUpdateNode
"""

import sys
import time
from pathlib import Path

try:
    import teleopcore.xrio as xrio
    import teleopcore.oxr as oxr
    import teleopcore.plugin_manager as pm
    from teleopcore.retargeting_engine import RetargeterExecutor, GripperRetargeter
    from teleopcore.retargeting_engine.xrio import ControllersInput, XrioUpdateNode
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore is built and installed")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def main():
    # Step 1: Create XRIO session builder
    builder = xrio.XrioSessionBuilder()
    
    # Step 2: Create XRIO update node and input nodes
    xrio_update = XrioUpdateNode(builder, app_name="ExternalOXRExample")
    controllers = ControllersInput(builder)
    controllers.connect_trigger(xrio_update.trigger())
    
    # Step 3: Build retargeting graph
    gripper = GripperRetargeter(name="gripper")
    gripper.connect_controllers(controllers.left(), controllers.right())
    
    # Step 4: Create executor
    executor = RetargeterExecutor([gripper])
    
    # Step 5: Get required OpenXR extensions from the builder
    required_extensions = builder.get_required_extensions()
    print(f"Required OpenXR extensions: {required_extensions}")
    
    # Step 6: Create your own OpenXR session with the required extensions
    # You can add additional custom extensions here if needed
    custom_extensions = []  # Add any custom extensions you need
    all_extensions = required_extensions + custom_extensions
    
    oxr_session = oxr.OpenXRSession.create("ExternalOXRExample", all_extensions)
    if oxr_session is None:
        print("Failed to create OpenXR session")
        return 1
    
    print("OpenXR session created successfully")
    
    # Step 7: Initialize plugin (if available)
    plugin_context = None
    if PLUGIN_ROOT_DIR.exists():
        manager = pm.PluginManager([str(PLUGIN_ROOT_DIR)])
        if PLUGIN_NAME in manager.get_plugin_names():
            plugin_context = manager.start(PLUGIN_NAME, PLUGIN_ROOT_ID)
    
    # Step 8: Enter the OpenXR session context and set handles
    with oxr_session:
        # Set the OpenXR handles on the update node
        xrio_update.set_oxr_handles(oxr_session.get_handles())
        
        print("Retargeting graph ready to execute\n")
        
        # Run control loop
        # The OpenXR session is managed by you (the with statement above)
        # The XRIO session is managed by XrioUpdateNode
        if plugin_context:
            with plugin_context:
                return run_loop(executor)
        else:
            return run_loop(executor)


def run_loop(executor):
    """Run the control loop."""
    start_time = time.time()
    frame_count = 0
    
    print("\nStarting control loop (press Ctrl+C to exit)...")
    print("Move the VR controllers and squeeze the triggers to control grippers\n")
    
    try:
        while time.time() - start_time < 20.0:
            # Execute the graph (xrio_update will update the XRIO session)
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
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    
    print(f"\nCompleted {frame_count} frames in {time.time() - start_time:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

