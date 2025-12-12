#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test script for ControllerTracker with simplified API.

Demonstrates:
- Snapshot mode for continuous state queries
- Event stream mode for input changes
- Separate pose queries
"""

import sys
import time

try:
    import teleopcore.xrio as xrio
    import teleopcore.oxr as oxr
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure the module is built")
    sys.exit(1)

print("=" * 80)
print("Controller Tracker Test - Simplified API")
print("=" * 80)
print()

# Test 1: Create controller tracker (handles both controllers)
print("[Test 1] Creating controller tracker...")
controller_tracker = xrio.ControllerTracker()
print(f"✓ {controller_tracker.get_name()} created")
print()

# Test 2: Create builder and add tracker
print("[Test 2] Creating builder...")
builder = xrio.TeleopSessionBuilder()
builder.add_tracker(controller_tracker)
print("✓ Tracker added to builder")
print()

# Test 3: Initialize
print("[Test 3] Creating OpenXR session and initializing...")

# Get required extensions
required_extensions = builder.get_required_extensions()
print(f"Required extensions: {required_extensions if required_extensions else 'None (uses core OpenXR)'}")

# Create OpenXR session
oxr_session = oxr.OpenXRSession.create("ControllerTrackerTest", required_extensions)
if oxr_session is None:
    print("❌ Failed to create OpenXR session")
    sys.exit(1)

# Use context managers for proper RAII cleanup
with oxr_session:
    handles = oxr_session.get_handles()
    
    # Create teleop session
    session = builder.build(handles)
    if session is None:
        print("❌ Failed to initialize")
        sys.exit(1)
    
    with session:
        print("✅ OpenXR session initialized")
        print()
        
        # Test 4: Initial update
        print("[Test 4] Testing initial data retrieval...")
        if not session.update():
            print("❌ Update failed")
            sys.exit(1)
        
        print("✓ Update successful")
        print()
        
        # Test 5: Check initial controller state (snapshot mode)
        print("[Test 5] Checking controller state (snapshot mode)...")
        left_snap = controller_tracker.get_snapshot(xrio.Hand.Left)
        right_snap = controller_tracker.get_snapshot(xrio.Hand.Right)
        print(f"  Left controller: {'ACTIVE' if left_snap.is_active else 'INACTIVE'}")
        print(f"  Right controller: {'ACTIVE' if right_snap.is_active else 'INACTIVE'}")
        
        if left_snap.is_active and left_snap.grip_pose.is_valid:
            pos = left_snap.grip_pose.position
            print(f"  Left grip position: [{pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f}]")
        
        if right_snap.is_active and right_snap.grip_pose.is_valid:
            pos = right_snap.grip_pose.position
            print(f"  Right grip position: [{pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f}]")
        print()
        
        # Test 6: Available inputs
        print("[Test 6] Available controller inputs:")
        # List all inputs except COUNT
        for input_type in [xrio.ControllerInput.PrimaryClick, xrio.ControllerInput.SecondaryClick,
                          xrio.ControllerInput.ThumbstickX, xrio.ControllerInput.ThumbstickY,
                          xrio.ControllerInput.ThumbstickClick, xrio.ControllerInput.SqueezeValue,
                          xrio.ControllerInput.TriggerValue]:
            print(f"  - {input_type.name}")
        print()
        
        # Test 7: Run tracking loop
        print("[Test 7] Running controller tracking loop (10 seconds)...")
        print("Press buttons or move controls to see events!")
        print()
        
        # Clear any initial events
        controller_tracker.clear_events(xrio.Hand.Left)
        controller_tracker.clear_events(xrio.Hand.Right)
        
        frame_count = 0
        start_time = time.time()
        last_snapshot_print = start_time
        
        try:
            while time.time() - start_time < 10.0:
                if not session.update():
                    print("Update failed")
                    break
                
                # EVENT STREAM MODE: Get all input changes
                left_events = controller_tracker.get_events(xrio.Hand.Left)
                right_events = controller_tracker.get_events(xrio.Hand.Right)
                
                elapsed = time.time() - start_time
                
                # Print left controller events
                for event in left_events:
                    input_name = event.input.name
                    value = event.value
                    
                    # Format value based on input type
                    if 'Click' in input_name:
                        state = "PRESSED" if value > 0.5 else "released"
                        print(f"  [{elapsed:5.2f}s] LEFT  {input_name}: {state}")
                    else:
                        print(f"  [{elapsed:5.2f}s] LEFT  {input_name}: {value:.2f}")
                
                # Print right controller events
                for event in right_events:
                    input_name = event.input.name
                    value = event.value
                    
                    if 'Click' in input_name:
                        state = "PRESSED" if value > 0.5 else "released"
                        print(f"  [{elapsed:5.2f}s] RIGHT {input_name}: {state}")
                    else:
                        print(f"  [{elapsed:5.2f}s] RIGHT {input_name}: {value:.2f}")
                
                # SNAPSHOT MODE: Periodic status summary (every 2 seconds)
                current_time = time.time()
                if current_time - last_snapshot_print >= 2.0:
                    elapsed = current_time - start_time
                    left_snap = controller_tracker.get_snapshot(xrio.Hand.Left)
                    right_snap = controller_tracker.get_snapshot(xrio.Hand.Right)
                    
                    # Show current state using array indexing
                    left_trigger = left_snap.inputs[xrio.ControllerInput.TriggerValue]
                    left_squeeze = left_snap.inputs[xrio.ControllerInput.SqueezeValue]
                    left_stick_x = left_snap.inputs[xrio.ControllerInput.ThumbstickX]
                    left_stick_y = left_snap.inputs[xrio.ControllerInput.ThumbstickY]
                    
                    right_trigger = right_snap.inputs[xrio.ControllerInput.TriggerValue]
                    right_squeeze = right_snap.inputs[xrio.ControllerInput.SqueezeValue]
                    right_stick_x = right_snap.inputs[xrio.ControllerInput.ThumbstickX]
                    right_stick_y = right_snap.inputs[xrio.ControllerInput.ThumbstickY]
                    
                    left_status = f"Trig={left_trigger:.2f} Sq={left_squeeze:.2f}"
                    if abs(left_stick_x) > 0.1 or abs(left_stick_y) > 0.1:
                        left_status += f" Stick=({left_stick_x:+.2f},{left_stick_y:+.2f})"
                    
                    right_status = f"Trig={right_trigger:.2f} Sq={right_squeeze:.2f}"
                    if abs(right_stick_x) > 0.1 or abs(right_stick_y) > 0.1:
                        right_status += f" Stick=({right_stick_x:+.2f},{right_stick_y:+.2f})"
                    
                    print(f"  [{elapsed:5.2f}s] Frame {frame_count:4d} | L: {left_status} | R: {right_status}")
                    last_snapshot_print = current_time
                
                frame_count += 1
                time.sleep(0.016)  # ~60 FPS
                
        except KeyboardInterrupt:
            print("\n⚠️  Interrupted by user")
        
        print()
        print(f"✓ Processed {frame_count} frames")
        print()
        
        # Test 8: Show final statistics
        print("[Test 8] Final controller state...")
        
        def print_controller_summary(hand_name, hand):
            snapshot = controller_tracker.get_snapshot(hand)
            print(f"  {hand_name} Controller:")
            if snapshot.is_active:
                print(f"    Status: ACTIVE")
                
                # Pose queries (independent of snapshot)
                grip = controller_tracker.get_grip_pose(hand)
                aim = controller_tracker.get_aim_pose(hand)
                
                if grip.is_valid:
                    pos = grip.position
                    print(f"    Grip position: [{pos[0]:+.3f}, {pos[1]:+.3f}, {pos[2]:+.3f}]")
                
                if aim.is_valid:
                    pos = aim.position
                    print(f"    Aim position: [{pos[0]:+.3f}, {pos[1]:+.3f}, {pos[2]:+.3f}]")
                
                # Input values using array access
                inputs = snapshot.inputs
                print(f"    Trigger: {inputs[xrio.ControllerInput.TriggerValue]:.2f}")
                print(f"    Squeeze: {inputs[xrio.ControllerInput.SqueezeValue]:.2f}")
                print(f"    Thumbstick: ({inputs[xrio.ControllerInput.ThumbstickX]:+.2f}, "
                      f"{inputs[xrio.ControllerInput.ThumbstickY]:+.2f})")
                print(f"    Primary: {'PRESSED' if inputs[xrio.ControllerInput.PrimaryClick] > 0.5 else 'released'}")
                print(f"    Secondary: {'PRESSED' if inputs[xrio.ControllerInput.SecondaryClick] > 0.5 else 'released'}")
            else:
                print(f"    Status: INACTIVE")
        
        print_controller_summary("Left", xrio.Hand.Left)
        print()
        print_controller_summary("Right", xrio.Hand.Right)
        print()
        
        # Cleanup
        print("[Test 9] Cleanup...")
        print("✓ Resources will be cleaned up when exiting 'with' blocks (RAII)")
        print()

print("=" * 80)
print("✅ All tests passed")
print("=" * 80)
print()
print("API Benefits:")
print("  ✓ Simple: One tracker per controller")
print("  ✓ Clean: All inputs as floats in array")
print("  ✓ Event stream: get_events() returns all changes")
print("  ✓ Snapshot: get_snapshot() for current state")
print("  ✓ Poses: Separate from input events")
print("=" * 80)
