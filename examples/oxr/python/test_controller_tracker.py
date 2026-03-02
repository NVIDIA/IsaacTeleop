# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test script for ControllerTracker with simplified API.

Demonstrates:
- Getting left and right controller data via get_left_controller() and get_right_controller()
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
        left_tracked = controller_tracker.get_left_controller(session)
        right_tracked = controller_tracker.get_right_controller(session)

        if left_tracked.data is not None and left_tracked.data.grip_pose.is_valid:
            pos = left_tracked.data.grip_pose.pose.position
            print(f"  Left grip:  [{pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f}]")
        else:
            print("  Left:  inactive")

        if right_tracked.data is not None and right_tracked.data.grip_pose.is_valid:
            pos = right_tracked.data.grip_pose.pose.position
            print(f"  Right grip: [{pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f}]")
        else:
            print("  Right: inactive")
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
                    left_tracked = controller_tracker.get_left_controller(session)
                    right_tracked = controller_tracker.get_right_controller(session)

                    print(f"  [{elapsed:5.2f}s] Frame {frame_count:4d}")

                    left_data = left_tracked.data
                    if left_data is not None:
                        li = left_data.inputs
                        print(
                            f"    L: Trig={li.trigger_value:.2f} Sq={li.squeeze_value:.2f}"
                            f" Stick=({li.thumbstick_x:+.2f},{li.thumbstick_y:+.2f})"
                            f" Btn=[{int(li.primary_click)}{int(li.secondary_click)}{int(li.thumbstick_click)}]"
                        )
                    else:
                        print("    L: INACTIVE")

                    right_data = right_tracked.data
                    if right_data is not None:
                        ri = right_data.inputs
                        print(
                            f"    R: Trig={ri.trigger_value:.2f} Sq={ri.squeeze_value:.2f}"
                            f" Stick=({ri.thumbstick_x:+.2f},{ri.thumbstick_y:+.2f})"
                            f" Btn=[{int(ri.primary_click)}{int(ri.secondary_click)}{int(ri.thumbstick_click)}]"
                        )
                    else:
                        print("    R: INACTIVE")
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

        def print_controller_summary(hand_name, tracked):
            print(f"  {hand_name} Controller:")
            if tracked.data is not None:
                pos = tracked.data.grip_pose.pose.position
                print(f"    Grip position: [{pos.x:+.3f}, {pos.y:+.3f}, {pos.z:+.3f}]")
                pos = tracked.data.aim_pose.pose.position
                print(f"    Aim position:  [{pos.x:+.3f}, {pos.y:+.3f}, {pos.z:+.3f}]")
                inputs = tracked.data.inputs
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
                print("    inactive")

        left_tracked = controller_tracker.get_left_controller(session)
        right_tracked = controller_tracker.get_right_controller(session)
        print_controller_summary("Left", left_tracked)
        print()
        print_controller_summary("Right", right_tracked)
        print()

        # Cleanup
        print("[Test 9] Cleanup...")
        print("✓ Resources will be cleaned up when exiting 'with' blocks (RAII)")
        print()

print("=" * 80)
print("✅ All tests passed")
print("=" * 80)
