#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test controller synthetic hands plugin using Plugin Manager.

This test:
1. Uses PluginManager to discover and launch the plugin
2. Queries available devices from the manifest
3. Starts the OpenXR session
4. Uses HandTracker to read the injected hands
5. Periodically polls plugin health

Note: Plugin crashes will raise pm.PluginCrashException
"""

import sys
import time
import os
from pathlib import Path

import teleopcore.xrio as xrio
import teleopcore.oxr as oxr
import teleopcore.plugin_manager as pm

# Paths
# The test will look for plugins in the install directory relative to this script
# This script is in install/examples/oxr/python
# Plugins are in install/plugins
PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"

def run_test():
    print("=" * 80)
    print("Controller Synthetic Hands Plugin Test")
    print("=" * 80)
    print()

    if not PLUGIN_ROOT_DIR.exists():
        print(f"Error: Plugin directory not found at {PLUGIN_ROOT_DIR}")
        print("Please build and install the project first.")
        return

    # 1. Initialize Plugin Manager
    print("[Step 1] Initializing Plugin Manager...")
    print(f"  Search path: {PLUGIN_ROOT_DIR}")
    manager = pm.PluginManager([str(PLUGIN_ROOT_DIR)])
    
    plugins = manager.get_plugin_names()
    print(f"  Discovered plugins: {plugins}")
    
    plugin_name = "controller_synthetic_hands"
    plugin_root_id = "synthetic_hands"
    
    if plugin_name not in plugins:
        print(f"  ✗ {plugin_name} not found")
        return

    # 2. Query Plugin Devices
    print("[Step 2] Querying plugin devices...")
    devices = manager.query_devices(plugin_name)
    print(f"  ✓ Available devices: {devices}")
    print()

    # 3. Start Plugin and Create Reader Session
    print("[Step 3] Starting plugin and reader session...")
    extensions = [
        "XR_KHR_convert_timespec_time",
        "XR_MND_headless",
        "XR_EXT_hand_tracking"
    ]
    
    with (
        manager.start(plugin_name, plugin_root_id) as plugin,
        oxr.OpenXRSession.create("HandReader", extensions) as oxr_session
    ):
        print("  ✓ Plugin started")
        print("  ✓ Reader session created")
        print()

        handles = oxr_session.get_handles()
        
        hand_tracker = xrio.HandTracker()
        builder = xrio.XrioSessionBuilder()
        builder.add_tracker(hand_tracker)
        
        with builder.build(handles) as xrio_session:
            if not xrio_session:
                print("  ✗ Failed to create xrio session")
                return
            
            print("  ✓ Xrio session created")
            print()

            # 4. Loop and Read with periodic health checks
            print("[Step 4] Reading data (10 seconds)...")
            start_time = time.time()
            frame_count = 0
            
            while time.time() - start_time < 10.0:
                # Poll plugin health every ~1 second
                if frame_count % 60 == 0:
                    try:
                        plugin.check_health() # Throws PluginCrashException if plugin crashed
                    except pm.PluginCrashException as e:
                        print(f"Plugin crashed: {e}")
                        break
                
                if not xrio_session.update():
                    print("  ✗ Reader session update failed")
                    break
                
                if frame_count % 60 == 0:
                    left = hand_tracker.get_left_hand()
                    right = hand_tracker.get_right_hand()
                    
                    print(f"Frame {frame_count}:")
                    print(f"  Left Hand: {'ACTIVE' if left.is_active else 'INACTIVE'}")
                    print(f"  Right Hand: {'ACTIVE' if right.is_active else 'INACTIVE'}")
                    
                    if left.is_active:
                        wrist = left.get_joint(xrio.JOINT_WRIST)
                        if wrist.is_valid:
                            print(f"    Left Wrist: {wrist.position}")
                    print()
                    
                frame_count += 1
                time.sleep(0.016)
    
    # Plugin automatically stopped when exiting 'with' block
    # If plugin crashed, PluginCrashException will be raised during stop()
    print("[Cleanup]")
    print("  ✓ Plugin stopped")
    print("  ✓ Done")

if __name__ == "__main__":
    run_test()
