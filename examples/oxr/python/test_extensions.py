#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test get_required_extensions() API

Demonstrates how to query required extensions before initialization.
Useful when creating external OpenXR sessions.
"""

import sys
import teleopcore.xrio as xrio
import teleopcore.oxr as oxr

print("=" * 80)
print("OpenXR Required Extensions Test")
print("=" * 80)
print()

# Test 1: Hand tracker only
print("[Test 1] HandTracker extensions")
hand_tracker = xrio.HandTracker()

builder1 = xrio.XrioSessionBuilder()
builder1.add_tracker(hand_tracker)

extensions1 = builder1.get_required_extensions()
print(f"  Required extensions: {len(extensions1)}")
for ext in extensions1:
    print(f"    - {ext}")
print()

# Test 2: Head tracker only
print("[Test 2] HeadTracker extensions")
head_tracker = xrio.HeadTracker()

builder2 = xrio.XrioSessionBuilder()
builder2.add_tracker(head_tracker)

extensions2 = builder2.get_required_extensions()
print(f"  Required extensions: {len(extensions2)}")
for ext in extensions2:
    print(f"    - {ext}")
print()

# Test 3: Both trackers
print("[Test 3] HandTracker + HeadTracker extensions")
hand_tracker3 = xrio.HandTracker()
head_tracker3 = xrio.HeadTracker()

builder3 = xrio.XrioSessionBuilder()
builder3.add_tracker(hand_tracker3)
builder3.add_tracker(head_tracker3)

extensions3 = builder3.get_required_extensions()
print(f"  Required extensions: {len(extensions3)}")
for ext in extensions3:
    print(f"    - {ext}")
print()

# Test 4: Use case - query before creating external session
print("[Test 4] Use case: Query before external session creation")
print()
print("Scenario: You want to create your own OpenXR session")
print("          and pass it to the manager.")
print()

hand = xrio.HandTracker()
head = xrio.HeadTracker()

builder = xrio.XrioSessionBuilder()
builder.add_tracker(hand)
builder.add_tracker(head)

# Query extensions BEFORE initializing
required_exts = builder.get_required_extensions()

print("Step 1: Add trackers to manager")
print("Step 2: Query required extensions:")
for ext in required_exts:
    print(f"  - {ext}")
print()
print("Step 3: Create your own OpenXR instance with these extensions")
print("        (in C++ or custom code)")
print()
print("Step 4: Pass handles to builder.build(handles)")
print()

# Now initialize normally to show it works
print("[Test 5] Normal initialization with queried extensions (RAII)")

# Create OpenXR session with the queried extensions
oxr_session = oxr.OpenXRSession.create("ExtensionTest", required_exts)
if oxr_session is None:
    print("  ❌ Failed to create OpenXR session")
else:
    # Use context managers for proper RAII cleanup
    with oxr_session:
        handles = oxr_session.get_handles()
        session = builder.build(handles)
        
        if session is not None:
            with session:
                print("  ✅ Initialized successfully")
                
                # Quick update test
                if session.update():
                    left = hand.get_left_hand()
                    head_pose = head.get_head()
                    print(f"  ✅ Update successful")
                    print(f"    Hands: {'ACTIVE' if left.is_active else 'INACTIVE'}")
                    print(f"    Head:  {'VALID' if head_pose.is_valid else 'INVALID'}")
                
                # Session will be cleaned up when exiting 'with' block (RAII)
        else:
            print("  ❌ Failed to initialize")

print()
print("=" * 80)
print("✅ Extension query test complete")
print("=" * 80)
print()
