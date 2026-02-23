# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test script for ControllerTracker with simplified API.

Demonstrates:
- Getting complete controller data for both left and right controllers
"""

import sys
import time

import isaacteleop.deviceio as deviceio
import isaacteleop.oxr as oxr

print("=" * 80)
print("Controller Tracker Test")
print("=" * 80)
print()

# Test 1: Create controller tracker (handles both controllers)
print("[Test 1] Creating controller tracker...")
controller_tracker = deviceio.ControllerTracker()
print(f"✓ {controller_tracker.get_name()} created")
print()

# Test 2: Query required extensions
print("[Test 2] Querying required extensions...")
trackers = [controller_tracker]
required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
print(
    f"Required extensions: {required_extensions if required_extensions else 'None (uses core OpenXR)'}"
)
print()

# Test 3: Initialize
print("[Test 3] Creating OpenXR session and initializing...")

# Use context managers for proper RAII cleanup
with oxr.OpenXRSession("ControllerTrackerTest", required_extensions) as oxr_session:
    handles = oxr_session.get_handles()

    # Run deviceio session with trackers (throws exception on failure)
    with deviceio.DeviceIOSession.run(trackers, handles) as session:
        print("✅ OpenXR session initialized")
        print()

        # Test 4: Initial update
        print("[Test 4] Testing initial data retrieval...")
        if not session.update():
            print("❌ Update failed")
            sys.exit(1)

        print("✓ Update successful")
        print()

        # Test 5: Check initial controller state
        print("[Test 5] Checking controller state...")
        left_snap = controller_tracker.get_left_controller(session)
        right_snap = controller_tracker.get_right_controller(session)
        print(
            f"  Left controller: {'ACTIVE' if left_snap and left_snap.is_active else 'INACTIVE'}"
        )
        print(
            f"  Right controller: {'ACTIVE' if right_snap and right_snap.is_active else 'INACTIVE'}"
        )

        if left_snap and left_snap.is_active and left_snap.grip_pose.is_valid:
            pos = left_snap.grip_pose.pose.position
            print(f"  Left grip position: [{pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f}]")

        if right_snap and right_snap.is_active and right_snap.grip_pose.is_valid:
            pos = right_snap.grip_pose.pose.position
            print(f"  Right grip position: [{pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f}]")
        print()

        # Test 6: Available inputs
        print("[Test 6] Available controller inputs:")
        print("  Buttons: primary_click, secondary_click, thumbstick_click")
        print("  Axes: thumbstick_x, thumbstick_y, squeeze_value, trigger_value")
        print()

        # Test 7: Run tracking loop
        print("[Test 7] Running controller tracking loop (10 seconds)...")
        print("Press buttons or move controls to see state!")
        print()

        frame_count = 0
        start_time = time.time()
        last_status_print = start_time

        try:
            while time.time() - start_time < 10.0:
                if not session.update():
                    print("Update failed")
                    break

                # Get current controller data
                current_time = time.time()
                if current_time - last_status_print >= 0.5:  # Print every 0.5 seconds
                    elapsed = current_time - start_time
                    left_snap = controller_tracker.get_left_controller(session)
                    right_snap = controller_tracker.get_right_controller(session)

                    # Show current state
                    left_trigger = left_snap.inputs.trigger_value if left_snap else 0.0
                    left_squeeze = left_snap.inputs.squeeze_value if left_snap else 0.0
                    left_stick_x = left_snap.inputs.thumbstick_x if left_snap else 0.0
                    left_stick_y = left_snap.inputs.thumbstick_y if left_snap else 0.0
                    left_primary = (
                        left_snap.inputs.primary_click if left_snap else False
                    )
                    left_secondary = (
                        left_snap.inputs.secondary_click if left_snap else False
                    )

                    right_trigger = (
                        right_snap.inputs.trigger_value if right_snap else 0.0
                    )
                    right_squeeze = (
                        right_snap.inputs.squeeze_value if right_snap else 0.0
                    )
                    right_stick_x = (
                        right_snap.inputs.thumbstick_x if right_snap else 0.0
                    )
                    right_stick_y = (
                        right_snap.inputs.thumbstick_y if right_snap else 0.0
                    )
                    right_primary = (
                        right_snap.inputs.primary_click if right_snap else False
                    )
                    right_secondary = (
                        right_snap.inputs.secondary_click if right_snap else False
                    )

                    # Build status strings
                    left_status = f"Trig={left_trigger:.2f} Sq={left_squeeze:.2f}"
                    if abs(left_stick_x) > 0.1 or abs(left_stick_y) > 0.1:
                        left_status += (
                            f" Stick=({left_stick_x:+.2f},{left_stick_y:+.2f})"
                        )
                    if left_primary:
                        left_status += " [X]"
                    if left_secondary:
                        left_status += " [Y]"

                    right_status = f"Trig={right_trigger:.2f} Sq={right_squeeze:.2f}"
                    if abs(right_stick_x) > 0.1 or abs(right_stick_y) > 0.1:
                        right_status += (
                            f" Stick=({right_stick_x:+.2f},{right_stick_y:+.2f})"
                        )
                    if right_primary:
                        right_status += " [A]"
                    if right_secondary:
                        right_status += " [B]"

                    print(
                        f"  [{elapsed:5.2f}s] Frame {frame_count:4d} | L: {left_status} | R: {right_status}"
                    )
                    last_status_print = current_time

                frame_count += 1
                time.sleep(0.016)  # ~60 FPS

        except KeyboardInterrupt:
            print("\n⚠️  Interrupted by user")

        print()
        print(f"✓ Processed {frame_count} frames")
        print()

        # Test 8: Show final statistics
        print("[Test 8] Final controller state...")

        def print_controller_summary(hand_name, snapshot):
            print(f"  {hand_name} Controller:")
            if snapshot and snapshot.is_active:
                print("    Status: ACTIVE")

                # Poses from snapshot
                grip = snapshot.grip_pose
                aim = snapshot.aim_pose

                if grip.is_valid:
                    pos = grip.pose.position
                    print(
                        f"    Grip position: [{pos.x:+.3f}, {pos.y:+.3f}, {pos.z:+.3f}]"
                    )

                if aim.is_valid:
                    pos = aim.pose.position
                    print(
                        f"    Aim position: [{pos.x:+.3f}, {pos.y:+.3f}, {pos.z:+.3f}]"
                    )

                # Input values
                inputs = snapshot.inputs
                print(f"    Trigger: {inputs.trigger_value:.2f}")
                print(f"    Squeeze: {inputs.squeeze_value:.2f}")
                print(
                    f"    Thumbstick: ({inputs.thumbstick_x:+.2f}, {inputs.thumbstick_y:+.2f})"
                )
                print(
                    f"    Primary: {'PRESSED' if inputs.primary_click else 'released'}"
                )
                print(
                    f"    Secondary: {'PRESSED' if inputs.secondary_click else 'released'}"
                )
            else:
                print("    Status: INACTIVE")

        left_snap = controller_tracker.get_left_controller(session)
        right_snap = controller_tracker.get_right_controller(session)
        print_controller_summary("Left", left_snap)
        print()
        print_controller_summary("Right", right_snap)
        print()

        # Cleanup
        print("[Test 9] Cleanup...")
        print("✓ Resources will be cleaned up when exiting 'with' blocks (RAII)")
        print()

print("=" * 80)
print("✅ All tests passed")
print("=" * 80)
