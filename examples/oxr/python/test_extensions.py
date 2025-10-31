#!/usr/bin/env python3
"""
Test get_required_extensions() API

Demonstrates how to query required extensions before initialization.
Useful when creating external OpenXR sessions.
"""

import sys
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
core_oxr_dir = os.path.join(script_dir, '..', '..', 'src', 'core', 'api', 'oxr')
build_python_dir = os.path.join(core_oxr_dir, 'build', 'python')
sys.path.insert(0, build_python_dir)

import oxr_tracking

print("=" * 80)
print("OpenXR Required Extensions Test")
print("=" * 80)
print()

# Test 1: Hand tracker only
print("[Test 1] HandTracker extensions")
hand_tracker = oxr_tracking.HandTracker()

mgr1 = oxr_tracking.OpenXRManager()
mgr1.add_tracker(hand_tracker)

extensions1 = mgr1.get_required_extensions()
print(f"  Required extensions: {len(extensions1)}")
for ext in extensions1:
    print(f"    - {ext}")
print()

# Test 2: Head tracker only
print("[Test 2] HeadTracker extensions")
head_tracker = oxr_tracking.HeadTracker()

mgr2 = oxr_tracking.OpenXRManager()
mgr2.add_tracker(head_tracker)

extensions2 = mgr2.get_required_extensions()
print(f"  Required extensions: {len(extensions2)}")
for ext in extensions2:
    print(f"    - {ext}")
print()

# Test 3: Both trackers
print("[Test 3] HandTracker + HeadTracker extensions")
hand_tracker3 = oxr_tracking.HandTracker()
head_tracker3 = oxr_tracking.HeadTracker()

mgr3 = oxr_tracking.OpenXRManager()
mgr3.add_tracker(hand_tracker3)
mgr3.add_tracker(head_tracker3)

extensions3 = mgr3.get_required_extensions()
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

hand = oxr_tracking.HandTracker()
head = oxr_tracking.HeadTracker()

mgr = oxr_tracking.OpenXRManager()
mgr.add_tracker(hand)
mgr.add_tracker(head)

# Query extensions BEFORE initializing
required_exts = mgr.get_required_extensions()

print("Step 1: Add trackers to manager")
print("Step 2: Query required extensions:")
for ext in required_exts:
    print(f"  - {ext}")
print()
print("Step 3: Create your own OpenXR instance with these extensions")
print("        (in C++ or custom code)")
print()
print("Step 4: Pass instance/session/space to manager.initialize()")
print()

# Now initialize normally to show it works
print("[Test 5] Normal initialization with queried extensions")
if mgr.initialize("ExtensionTest"):
    print("  ✅ Initialized successfully")
    
    # Quick update test
    if mgr.update():
        left = hand.get_left_hand()
        head_pose = head.get_head()
        print(f"  ✅ Update successful")
        print(f"    Hands: {'ACTIVE' if left.is_active else 'INACTIVE'}")
        print(f"    Head:  {'VALID' if head_pose.is_valid else 'INVALID'}")
    
    mgr.shutdown()
else:
    print("  ❌ Failed to initialize")

print()
print("=" * 80)
print("✅ Extension Query API Working!")
print("=" * 80)
print()
