#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Dex Hand Retargeting Example

Demonstrates using the DexHandRetargeter and DexMotionController modules
to retarget hand tracking data and motion controller inputs to robot hand joints.

This example shows:
1. DexMotionController - Simple VR controller-based hand control
2. DexHandRetargeter - Accurate hand tracking with dex_retargeting library (optional)
"""

import sys
import time
from pathlib import Path

try:
    import teleopcore.deviceio as deviceio
    import teleopcore.oxr as oxr
    import teleopcore.plugin_manager as pm
    from teleopcore.retargeting_engine.sources import HandsSource, ControllersSource
    from teleopcore.retargeting_engine.retargeters.isaac_lab import (
        DexMotionController,
        DexMotionControllerConfig,
        DexHandRetargeter,
        DexHandRetargeterConfig,
    )
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure TeleopCore is built and installed")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def example_dex_motion_controller():
    """Run DexMotionController example with VR controllers."""
    print("\n" + "=" * 80)
    print("  DexMotionController Example")
    print("=" * 80)
    print("\nMapping VR controller inputs to dexterous hand joints...")
    print("- Trigger: Controls index finger")
    print("- Squeeze: Controls middle finger")
    print("- Both: Controls thumb\n")
    
    # Create controller tracker
    controller_tracker = deviceio.ControllerTracker()
    
    # Create controllers source
    controllers = ControllersSource(controller_tracker, name="controllers")
    
    # Configure DexMotionController for 7-DOF hand
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
    left_config = DexMotionControllerConfig(
        hand_joint_names=hand_joint_names,
        controller_side="left",
    )
    left_controller = DexMotionController(left_config, name="dex_motion_left")
    
    # Connect to source
    connected = left_controller.connect({
        "controller_left": controllers.output("controller_left")
    })
    
    # Get required extensions and create OpenXR session
    trackers = [controller_tracker]
    required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
    
    with oxr.OpenXRSession.create("DexMotionControllerExample", required_extensions) as oxr_session:
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
                    run_motion_controller_loop(deviceio_session, connected)
            else:
                run_motion_controller_loop(deviceio_session, connected)
    
    return 0


def example_dex_hand_retargeter():
    """Run DexHandRetargeter example with hand tracking (requires dex-retargeting)."""
    print("\n" + "=" * 80)
    print("  DexHandRetargeter Example")
    print("=" * 80)
    print("\nUsing dex_retargeting library for accurate hand tracking...")
    print("Note: Requires dex-retargeting, scipy, and config files\n")
    
    # Check for required libraries
    try:
        import scipy
        from dex_retargeting.retargeting_config import RetargetingConfig
    except ImportError as e:
        print(f"❌ Required library not available: {e}")
        print("\nTo use DexHandRetargeter, install:")
        print("  pip install dex-retargeting scipy")
        return 1
    
    # Check for config files
    config_dir = Path(__file__).parent / "config" / "dex_retargeting"
    yaml_config = config_dir / "hand_left_config.yml"
    urdf_path = config_dir / "robot_hand.urdf"
    
    if not yaml_config.exists() or not urdf_path.exists():
        print(f"❌ Config files not found:")
        print(f"   YAML: {yaml_config}")
        print(f"   URDF: {urdf_path}")
        print("\nTo use DexHandRetargeter, provide:")
        print("1. URDF file describing your robot hand")
        print("2. YAML config file for dex_retargeting")
        print("\nSee IsaacLab examples for reference configs:")
        print("  IsaacLab/source/isaaclab_tasks/.../config/dex_retargeting/")
        return 1
    
    # Create hand tracker
    hand_tracker = deviceio.HandTracker()
    
    # Create hands source
    hands = HandsSource(hand_tracker, name="hands")
    
    # Configure DexHandRetargeter
    hand_joint_names = [
        "thumb_proximal_yaw_joint",
        "thumb_proximal_pitch_joint",
        "index_proximal_joint",
        "middle_proximal_joint",
        "ring_proximal_joint",
        "pinky_proximal_joint",
    ]
    
    retargeter_config = DexHandRetargeterConfig(
        hand_joint_names=hand_joint_names,
        hand_retargeting_config=str(yaml_config),
        hand_urdf=str(urdf_path),
        handtracking_to_baselink_frame_transform=(0, 0, 1, 1, 0, 0, 0, 1, 0),
        hand_side="left",
    )
    
    retargeter = DexHandRetargeter(retargeter_config, name="dex_hand_left")
    
    # Connect to source
    connected = retargeter.connect({
        "hand_left": hands.output("hand_left")
    })
    
    # Get required extensions and create OpenXR session
    trackers = [hand_tracker]
    required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
    
    with oxr.OpenXRSession.create("DexHandRetargeterExample", required_extensions) as oxr_session:
        handles = oxr_session.get_handles()
        
        # Create DeviceIO session with trackers
        with deviceio.DeviceIOSession.run(trackers, handles) as deviceio_session:
            # Run retargeting loop
            run_hand_retargeting_loop(deviceio_session, connected)
    
    return 0


def run_motion_controller_loop(deviceio_session, connected_module):
    """Run the motion controller loop."""
    start_time = time.time()
    frame_count = 0
    
    print("Running for 20 seconds...")
    print("=" * 80)
    
    while time.time() - start_time < 20.0:
        # Update DeviceIO session (polls trackers)
        deviceio_session.update()
        
        # Execute retargeting graph
        result = connected_module()
        
        # Access output joint angles
        hand_joints = result["hand_joints"]
        
        # Print every 0.5 seconds
        if frame_count % 30 == 0:
            elapsed = time.time() - start_time
            thumb = hand_joints[0]
            index = hand_joints[3]
            middle = hand_joints[5]
            print(f"[{elapsed:5.1f}s] Thumb: {thumb:6.3f}  Index: {index:6.3f}  Middle: {middle:6.3f}")
        
        frame_count += 1
        time.sleep(0.016)  # ~60 FPS
    
    print("=" * 80)
    print(f"✓ Completed {frame_count} frames in {time.time() - start_time:.1f}s")


def run_hand_retargeting_loop(deviceio_session, connected_module):
    """Run the hand retargeting loop."""
    start_time = time.time()
    frame_count = 0
    
    print("Running for 20 seconds...")
    print("Move your left hand in front of the tracking camera...")
    print("=" * 80)
    
    while time.time() - start_time < 20.0:
        # Update DeviceIO session (polls trackers)
        deviceio_session.update()
        
        # Execute retargeting graph
        result = connected_module()
        
        # Access output joint angles
        hand_joints = result["hand_joints"]
        
        # Print every 0.5 seconds (show first 3 joints)
        if frame_count % 30 == 0:
            elapsed = time.time() - start_time
            j1, j2, j3 = hand_joints[0], hand_joints[1], hand_joints[2]
            print(f"[{elapsed:5.1f}s] Joints: [{j1:6.3f}, {j2:6.3f}, {j3:6.3f}, ...]")
        
        frame_count += 1
        time.sleep(0.016)  # ~60 FPS
    
    print("=" * 80)
    print(f"✓ Completed {frame_count} frames in {time.time() - start_time:.1f}s")


def main():
    """Main entry point."""
    print("=" * 80)
    print("  Dex Hand Retargeting Examples")
    print("=" * 80)
    print("\nChoose example:")
    print("1. DexMotionController (simple, no extra dependencies)")
    print("2. DexHandRetargeter (requires dex-retargeting, config files)")
    print("3. Exit")
    
    choice = input("\nEnter choice (1-3): ").strip()
    
    if choice == "1":
        return example_dex_motion_controller()
    elif choice == "2":
        return example_dex_hand_retargeter()
    elif choice == "3":
        print("\nExiting...")
        return 0
    else:
        print(f"\n❌ Invalid choice: {choice}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

