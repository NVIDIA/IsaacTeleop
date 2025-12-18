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
import teleopcore.xrio as xrio
import teleopcore.oxr as oxr


def main():
    print("=" * 60)
    print("OpenXR Modular Tracking Example")
    print("=" * 60)
    print()
    
    # Create trackers independently
    print("Creating trackers...")
    hand_tracker = xrio.HandTracker()
    head_tracker = xrio.HeadTracker()
    print(f"✓ Created {hand_tracker.get_name()}")
    print(f"✓ Created {head_tracker.get_name()}")
    
    # Create builder and add trackers
    print("\nCreating builder and adding trackers...")
    builder = xrio.XrioSessionBuilder()
    builder.add_tracker(hand_tracker)
    builder.add_tracker(head_tracker)
    print("✓ Builder created and trackers added")
    
    # Get required extensions
    required_extensions = builder.get_required_extensions()
    
    # Create OpenXR session
    print("\nCreating OpenXR session...")
    oxr_session = oxr.OpenXRSession.create("ModularExample", required_extensions)
    if oxr_session is None:
        print("✗ Failed to create OpenXR session")
        return 1
    
    # Use context managers for proper RAII cleanup
    with oxr_session:
        handles = oxr_session.get_handles()
        print("✓ OpenXR session created")
        
        # Build xrio session from builder
        print("\nInitializing xrio session...")
        session = builder.build(handles)
        if session is None:
            print("✗ Failed to initialize")
            return 1
        
        with session:
            print("✓ Xrio session initialized with all trackers!")
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
                        left = hand_tracker.get_left_hand()
                        right = hand_tracker.get_right_hand()
                        
                        print(f"  Hands: Left={'ACTIVE' if left.is_active else 'INACTIVE':8s} | "
                              f"Right={'ACTIVE' if right.is_active else 'INACTIVE':8s}")
                        
                        if left.is_active:
                            wrist = left.get_joint(xrio.JOINT_WRIST)
                            if wrist.is_valid:
                                pos = wrist.position
                                print(f"    Left wrist: [{pos[0]:6.3f}, {pos[1]:6.3f}, {pos[2]:6.3f}]")

                        # Get head data (returns HeadPoseT from schema)
                        head = head_tracker.get_head()
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

