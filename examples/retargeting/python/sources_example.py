#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Retargeting Engine Sources Example

Demonstrates using the retargeting engine source modules with DeviceIO trackers.
Source modules wrap DeviceIO trackers and provide data in the standard retargeting
engine tensor format.

This example shows:
- Creating DeviceIO trackers (hand, head, controller)
- Wrapping them with retargeting engine source modules
- Using OutputCombiner to combine outputs from multiple sources
- Reading combined data in tensor format
- Printing tracking data in real-time
"""

import sys
import time
import teleopcore.deviceio as deviceio
import teleopcore.oxr as oxr
from teleopcore.retargeting_engine.sources import HandsSource, HeadSource, ControllersSource
from teleopcore.retargeting_engine.interface import OutputCombiner


def main():
    print("=" * 70)
    print("Retargeting Engine Sources Example")
    print("=" * 70)
    print()
    
    # ========================================================================
    # Step 1: Create DeviceIO trackers
    # ========================================================================
    print("[Step 1] Creating DeviceIO trackers...")
    hand_tracker = deviceio.HandTracker()
    head_tracker = deviceio.HeadTracker()
    controller_tracker = deviceio.ControllerTracker()
    print(f"  ✓ Created {hand_tracker.get_name()}")
    print(f"  ✓ Created {head_tracker.get_name()}")
    print(f"  ✓ Created {controller_tracker.get_name()}")
    
    # ========================================================================
    # Step 2: Get required OpenXR extensions
    # ========================================================================
    print("\n[Step 2] Querying required OpenXR extensions...")
    trackers = [hand_tracker, head_tracker, controller_tracker]
    required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
    print(f"  ✓ Required extensions: {', '.join(required_extensions)}")
    
    # ========================================================================
    # Step 3: Create OpenXR session
    # ========================================================================
    print("\n[Step 3] Creating OpenXR session...")
    oxr_session = oxr.OpenXRSession.create("RetargetingSourcesExample", required_extensions)
    
    with oxr_session:
        handles = oxr_session.get_handles()
        print("  ✓ OpenXR session created successfully")
        
        # ====================================================================
        # Step 4: Run DeviceIO session
        # ====================================================================
        print("\n[Step 4] Initializing DeviceIO session...")
        with deviceio.DeviceIOSession.run(trackers, handles) as session:
            print("  ✓ DeviceIO session initialized with all trackers")
            
            # ================================================================
            # Step 5: Create retargeting engine source modules
            # ================================================================
            print("\n[Step 5] Creating retargeting engine source modules...")
            hands_source = HandsSource(hand_tracker, session, name="hands")
            head_source = HeadSource(head_tracker, session, name="head")
            controllers_source = ControllersSource(controller_tracker, session, name="controllers")
            print("  ✓ Created HandsSource")
            print("  ✓ Created HeadSource")
            print("  ✓ Created ControllersSource")
            
            # ================================================================
            # Step 6: Create OutputCombiner to combine all source outputs
            # ================================================================
            print("\n[Step 6] Creating OutputCombiner to combine all sources...")
            combiner = OutputCombiner({
                # Hand outputs
                "hand_left": hands_source.output("hand_left"),
                "hand_right": hands_source.output("hand_right"),
                # Head output
                "head": head_source.output("head"),
                # Controller outputs
                "controller_left": controllers_source.output("controller_left"),
                "controller_right": controllers_source.output("controller_right"),
            })
            print("  ✓ Created OutputCombiner with 5 combined outputs")
            
            # ================================================================
            # Step 7: Main tracking loop
            # ================================================================
            print("\n[Step 7] Starting main tracking loop...")
            print("=" * 70)
            print("Tracking Data (10 seconds)")
            print("=" * 70)
            print()
            
            frame_count = 0
            start_time = time.time()
            
            while time.time() - start_time < 10.0:
                # Update session and all trackers
                if not session.update():
                    print("Update failed")
                    break
                
                # Print every 60 frames (~1 second)
                if frame_count % 60 == 0:
                    elapsed = time.time() - start_time
                    print(f"[{elapsed:4.1f}s] Frame {frame_count}")
                    print("-" * 70)
                    
                    # ====================================================
                    # Get ALL data from combiner in one call
                    # ====================================================
                    
                    # Execute combiner - returns all outputs combined
                    all_data = combiner({})
                    
                    # Extract hand data
                    left_hand = all_data["hand_left"]
                    left_positions = left_hand[0]  # (26, 3) array of joint positions
                    left_active = left_hand[4]     # is_active boolean
                    
                    right_hand = all_data["hand_right"]
                    right_positions = right_hand[0]  # (26, 3) array of joint positions
                    right_active = right_hand[4]     # is_active boolean
                    
                    print(f"  Hands:")
                    print(f"    Left:  {'ACTIVE' if left_active else 'INACTIVE'}")
                    if left_active:
                        wrist_idx = deviceio.JOINT_WRIST
                        wrist_pos = left_positions[wrist_idx]
                        print(f"      Wrist: [{wrist_pos[0]:6.3f}, {wrist_pos[1]:6.3f}, {wrist_pos[2]:6.3f}]")
                    
                    print(f"    Right: {'ACTIVE' if right_active else 'INACTIVE'}")
                    if right_active:
                        wrist_idx = deviceio.JOINT_WRIST
                        wrist_pos = right_positions[wrist_idx]
                        print(f"      Wrist: [{wrist_pos[0]:6.3f}, {wrist_pos[1]:6.3f}, {wrist_pos[2]:6.3f}]")
                    
                    # Extract head data
                    head = all_data["head"]
                    head_position = head[0]  # (3,) array [x, y, z]
                    head_valid = head[2]     # is_valid boolean
                    
                    print(f"  Head:")
                    print(f"    Status: {'VALID' if head_valid else 'INVALID'}")
                    if head_valid:
                        print(f"    Position: [{head_position[0]:6.3f}, {head_position[1]:6.3f}, {head_position[2]:6.3f}]")
                    
                    # Extract controller data
                    left_ctrl = all_data["controller_left"]
                    left_ctrl_active = left_ctrl[11]      # is_active boolean
                    left_trigger = left_ctrl[10]          # trigger_value float
                    
                    right_ctrl = all_data["controller_right"]
                    right_ctrl_active = right_ctrl[11]    # is_active boolean
                    right_trigger = right_ctrl[10]        # trigger_value float
                    
                    print(f"  Controllers:")
                    print(f"    Left:  {'ACTIVE' if left_ctrl_active else 'INACTIVE'}")
                    if left_ctrl_active:
                        print(f"      Trigger: {left_trigger:4.2f}")
                    
                    print(f"    Right: {'ACTIVE' if right_ctrl_active else 'INACTIVE'}")
                    if right_ctrl_active:
                        print(f"      Trigger: {right_trigger:4.2f}")
                    
                    print()
                
                frame_count += 1
                time.sleep(0.016)  # ~60 FPS
            
            # ================================================================
            # Cleanup
            # ================================================================
            print()
            print("=" * 70)
            print(f"Processed {frame_count} frames ({frame_count/10.0:.1f} FPS)")
            print("=" * 70)
            print("\nCleaning up...")
            print("  ✓ Resources will be cleaned up automatically (RAII)")
    
    print("\n✅ Example completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
