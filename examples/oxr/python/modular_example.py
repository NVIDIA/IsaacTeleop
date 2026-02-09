#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
OpenXR Modular Tracking Example

Demonstrates the modular architecture where you can:
- Create independent trackers
- Add only the trackers you need
- Easily extend with new tracker types
"""

import sys
import time
import isaacteleop.deviceio as deviceio
import isaacteleop.oxr as oxr


def main():
    print("=" * 60)
    print("OpenXR Modular Tracking Example")
    print("=" * 60)
    print()
    
    # Create trackers independently
    print("Creating trackers...")
    hand_tracker = deviceio.HandTracker()
    head_tracker = deviceio.HeadTracker()
    print(f"✓ Created {hand_tracker.get_name()}")
    print(f"✓ Created {head_tracker.get_name()}")
    
    # Get required extensions
    print("\nQuerying required extensions...")
    trackers = [hand_tracker, head_tracker]
    required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
    print(f"✓ Required extensions: {required_extensions}")
    
    # Create OpenXR session
    print("\nCreating OpenXR session...")
    with oxr.OpenXRSession("ModularExample", required_extensions) as oxr_session:
        handles = oxr_session.get_handles()
        print("✓ OpenXR session created")
        
        # Run deviceio session with trackers (throws exception on failure)
        print("\nRunning deviceio session with trackers...")
        with deviceio.DeviceIOSession.run(trackers, handles) as session:
            print("✓ DeviceIO session initialized with all trackers!")
            print()
            
            # Main tracking loop
            print("=" * 60)
            print("Tracking (10 seconds)...")
            print("=" * 60)
            print()
            
            frame_count = 0
            start_time = time.time()
            
            try:
                while time.time() - start_time < 10.0:
                    # Update session and all trackers
                    if not session.update():
                        print("Update failed")
                        break
                    
                    # Print every 60 frames (~1 second)
                    if frame_count % 60 == 0:
                        elapsed = time.time() - start_time
                        print(f"[{elapsed:4.1f}s] Frame {frame_count}")
                        
                        # Get hand data
                        left = hand_tracker.get_left_hand(session)
                        right = hand_tracker.get_right_hand(session)

                        print(f"  Hands: Left={'ACTIVE' if left.is_active else 'INACTIVE':8s} | "
                              f"Right={'ACTIVE' if right.is_active else 'INACTIVE':8s}")

                        if left.is_active:
                            wrist = left.joints[deviceio.JOINT_WRIST]
                            if wrist.is_valid:
                                pos = wrist.pose.position
                                print(f"    Left wrist: [{pos.x:6.3f}, {pos.y:6.3f}, {pos.z:6.3f}]")

                        # Get head data (returns HeadPoseT from schema)
                        head = head_tracker.get_head(session)
                        print(f"  Head: {'VALID' if head.is_valid else 'INVALID':8s}")

                        if head.is_valid and head.pose:
                            pos = head.pose.position
                            print(f"    Head position: [{pos.x:6.3f}, {pos.y:6.3f}, {pos.z:6.3f}]")

                        print()
                    
                    frame_count += 1
                    time.sleep(0.016)  # ~60 FPS
            
            except KeyboardInterrupt:
                print("\nInterrupted by user")
            
            # Cleanup
            print(f"\nProcessed {frame_count} frames")
            print("Cleaning up (RAII)...")
            print("✓ Resources will be cleaned up when exiting 'with' blocks")
    
    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

