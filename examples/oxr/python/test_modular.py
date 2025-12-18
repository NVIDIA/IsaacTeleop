#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test script for modular OpenXR tracking API
"""

import sys
import os
import time

try:
    import teleopcore.xrio as xrio
    import teleopcore.oxr as oxr
    import teleopcore.schema as schema
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure the module is built")
    sys.exit(1)

print("=" * 80)
print("OpenXR Modular Tracking API Test")
print("=" * 80)
print()

# Test 1: Create trackers
print("[Test 1] Creating trackers...")
hand_tracker = xrio.HandTracker()
head_tracker = xrio.HeadTracker()
print(f"✓ {hand_tracker.get_name()} created")
print(f"✓ {head_tracker.get_name()} created")
print()

# Test 2: Create builder
print("[Test 2] Creating builder...")
builder = xrio.XrioSessionBuilder()
print("✓ XrioSessionBuilder created")
print()

# Test 3: Add trackers
print("[Test 3] Adding trackers...")
builder.add_tracker(hand_tracker)
builder.add_tracker(head_tracker)
print("✓ Trackers added to builder")
print()

# Test 4: Initialize
print("[Test 4] Creating OpenXR session and initializing...")

# Get required extensions
required_extensions = builder.get_required_extensions()

# Create OpenXR session
oxr_session = oxr.OpenXRSession.create("ModularTest", required_extensions)
if oxr_session is None:
    print("❌ Failed to create OpenXR session")
    sys.exit(1)

# Use context managers for proper RAII cleanup
with oxr_session:
    handles = oxr_session.get_handles()
    
    # Create xrio session
    session = builder.build(handles)
    if session is None:
        print("❌ Failed to initialize")
        sys.exit(1)
    
    with session:
        print("✅ OpenXR session initialized")
        print()
        
        # Test 5: Update and get data
        print("[Test 5] Testing data retrieval...")
        if not session.update():
            print("❌ Update failed")
            sys.exit(1)
        
        print("✓ Update successful")
        print()
        
        # Test 6: Check hand data
        print("[Test 6] Checking hand tracking data...")
        left = hand_tracker.get_left_hand()
        right = hand_tracker.get_right_hand()
        print(f"  Left hand: {'ACTIVE' if left.is_active else 'INACTIVE'}")
        print(f"  Right hand: {'ACTIVE' if right.is_active else 'INACTIVE'}")
        
        if left.is_active:
            wrist = left.get_joint(xrio.JOINT_WRIST)
            if wrist.is_valid:
                pos = wrist.position
                print(f"  Left wrist position: [{pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f}]")
        print()

        # Test 7: Check head data (returns HeadPoseT from schema)
        print("[Test 7] Checking head tracking data...")
        head: schema.HeadPoseT = head_tracker.get_head()
        print(f"  Head: {'VALID' if head.is_valid else 'INVALID'}")

        if head.is_valid and head.pose:
            pos = head.pose.position
            ori = head.pose.orientation
            print(f"  Head position: [{pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f}]")
            print(f"  Head orientation: [{ori.x:.3f}, {ori.y:.3f}, {ori.z:.3f}, {ori.w:.3f}]")
        print()
        
        # Test 8: Run tracking loop
        print("[Test 8] Running tracking loop (5 seconds)...")
        frame_count = 0
        start_time = time.time()
        
        try:
            while time.time() - start_time < 5.0:
                if not session.update():
                    print("Update failed")
                    break
                
                if frame_count % 60 == 0:
                    elapsed = time.time() - start_time
                    left = hand_tracker.get_left_hand()
                    head = head_tracker.get_head()
                    print(f"  [{elapsed:4.1f}s] Frame {frame_count:3d}: "
                          f"Hands={'ACTIVE' if left.is_active else 'INACTIVE':8s} | "
                          f"Head={'VALID' if head.is_valid else 'INVALID':8s}")
                
                frame_count += 1
                time.sleep(0.016)
        except KeyboardInterrupt:
            print("\nInterrupted")
        
        print(f"✓ Processed {frame_count} frames")
        print()
        
        # Cleanup
        print("[Test 9] Cleanup...")
        print("✓ Resources will be cleaned up when exiting 'with' blocks (RAII)")
        print()

print("=" * 80)
print("✅ All tests passed")
print("=" * 80)

