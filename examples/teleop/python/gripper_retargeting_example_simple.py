#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Simplified Gripper Retargeting Example

Demonstrates the simplified TeleopSession API where input nodes automatically
create and register their trackers.
"""

import sys
import time
from pathlib import Path

try:
    import teleopcore.xrio as xrio
    from teleopcore.retargeting_engine import RetargeterExecutor, GripperRetargeter
    from teleopcore.retargeting_engine.xrio import ControllersInput
    from teleopcore.teleop_utils import TeleopSession, TeleopSessionConfig, PluginConfig
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore and all modules are built and installed")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def main():
    # Create XRIO session builder
    builder = xrio.XrioSessionBuilder()
    
    # Configure plugins (if available)
    plugins = []
    if PLUGIN_ROOT_DIR.exists():
        plugins.append(PluginConfig(
            plugin_name=PLUGIN_NAME,
            plugin_root_id=PLUGIN_ROOT_ID,
            search_paths=[PLUGIN_ROOT_DIR],
        ))
    
    # Create XRIO update node (will manage OpenXR/XRIO sessions internally)
    from teleopcore.retargeting_engine.xrio import XrioUpdateNode
    xrio_update = XrioUpdateNode(builder, app_name="SimplifiedGripperExample")
    
    # Create input nodes
    controllers = ControllersInput(builder)
    controllers.connect_trigger(xrio_update.trigger())
    
    # Build retargeting graph
    gripper = GripperRetargeter(name="gripper")
    gripper.connect_controllers(controllers.left(), controllers.right())
    executor = RetargeterExecutor([gripper])
    
    # Configure session
    config = TeleopSessionConfig(
        xrio_session_builder=builder,
        executor=executor,
        app_name="SimplifiedGripperExample",
        plugins=plugins,
        verbose=True
    )
    
    with TeleopSession(config) as session:
        start_time = time.time()
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
