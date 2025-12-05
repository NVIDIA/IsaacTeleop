#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Simplified Gripper Retargeting Example with External OpenXR Session

Demonstrates using TeleopSession with an externally managed OpenXR session.
This combines the simplicity of TeleopSession with the control of external OpenXR management.

Key differences from the simple example:
- You create and manage the OpenXR session
- You pass OpenXR handles to XrioUpdateNode
- TeleopSession still handles plugin management and execution loop
"""

import sys
import time
from pathlib import Path

try:
    import teleopcore.xrio as xrio
    import teleopcore.oxr as oxr
    from teleopcore.retargeting_engine import RetargeterExecutor, GripperRetargeter
    from teleopcore.retargeting_engine.xrio import ControllersInput, XrioUpdateNode
    from teleopcore.teleop_utils import TeleopSession, TeleopSessionConfig, PluginConfig
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore and all modules are built and installed")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def main():
    # Step 1: Create XRIO session builder
    builder = xrio.XrioSessionBuilder()
    
    # Step 2: Create XRIO update node and input nodes
    xrio_update = XrioUpdateNode(builder, app_name="SimplifiedExternalOXRExample")
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
    custom_extensions = []  # Add any custom extensions you need
    all_extensions = required_extensions + custom_extensions
    
    oxr_session = oxr.OpenXRSession.create("SimplifiedExternalOXRExample", all_extensions)
    if oxr_session is None:
        print("Failed to create OpenXR session")
        return 1
    
    print("OpenXR session created successfully")
    
    # Step 7: Configure plugins (if available)
    plugins = []
    if PLUGIN_ROOT_DIR.exists():
        plugins.append(PluginConfig(
            plugin_name=PLUGIN_NAME,
            plugin_root_id=PLUGIN_ROOT_ID,
            search_paths=[PLUGIN_ROOT_DIR],
        ))
    
    # Step 8: Enter the OpenXR session context and set handles
    with oxr_session:
        # Set the OpenXR handles on the update node
        xrio_update.set_oxr_handles(oxr_session.get_handles())
        
        # Configure TeleopSession
        config = TeleopSessionConfig(
            xrio_session_builder=builder,
            executor=executor,
            app_name="SimplifiedExternalOXRExample",
            plugins=plugins,
            verbose=True
        )
        
        print("TeleopSession configured\n")
        
        # Run TeleopSession
        # The OpenXR session is managed by you (the outer with statement)
        # The XRIO session is managed by XrioUpdateNode
        # TeleopSession handles plugins and execution
        with TeleopSession(config) as session:
            start_time = time.time()
            print("Control loop started (running for 20 seconds)...")
            print("Move the VR controllers and squeeze the triggers\n")
            
            while time.time() - start_time < 20.0:
                result = session.run()
                if result is None:
                    break
                
                # result[node_index][collection_index] = list of tensor values
                left_gripper = result[0][0][0]   # First node, first collection (left), first tensor
                right_gripper = result[0][1][0]  # First node, second collection (right), first tensor
                
                # Print every 0.5 seconds
                if session.frame_count % 30 == 0:
                    elapsed = time.time() - start_time
                    print(f"[{elapsed:5.1f}s] Left: {left_gripper:.2f}  Right: {right_gripper:.2f}")
                
                time.sleep(0.016)  # ~60 FPS
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

