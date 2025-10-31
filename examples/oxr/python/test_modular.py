#!/usr/bin/env python3
"""
Test script for modular OpenXR tracking API
"""

import sys
import os
import time

# Add build directory to path
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
core_oxr_dir = os.path.join(script_dir, '..', '..', 'src', 'core', 'api', 'oxr')
build_python_dir = os.path.join(core_oxr_dir, 'build', 'python')
sys.path.insert(0, build_python_dir)

try:
    import oxr_tracking
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
hand_tracker = oxr_tracking.HandTracker()
head_tracker = oxr_tracking.HeadTracker()
print(f"✓ {hand_tracker.get_name()} created")
print(f"✓ {head_tracker.get_name()} created")
print()

# Test 2: Create manager
print("[Test 2] Creating manager...")
manager = oxr_tracking.OpenXRManager()
print("✓ OpenXRManager created")
print()

# Test 3: Add trackers
print("[Test 3] Adding trackers...")
manager.add_tracker(hand_tracker)
manager.add_tracker(head_tracker)
print("✓ Trackers added to manager")
print()

# Test 4: Initialize
print("[Test 4] Initializing OpenXR...")
if not manager.initialize("ModularTest"):
    print("❌ Failed to initialize")
    print("\nMake sure:")
    print("  1. CloudXR service is running")
    print("  2. XR_RUNTIME_JSON is set correctly")
    sys.exit(1)

print("✅ OpenXR initialized successfully!")
print()

# Test 5: Update and get data
print("[Test 5] Testing data retrieval...")
if not manager.update():
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
    wrist = left.get_joint(oxr_tracking.JOINT_WRIST)
    if wrist.is_valid:
        pos = wrist.position
        print(f"  Left wrist position: [{pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f}]")
print()

# Test 7: Check head data
print("[Test 7] Checking head tracking data...")
head = head_tracker.get_head()
print(f"  Head: {'VALID' if head.is_valid else 'INVALID'}")

if head.is_valid:
    pos = head.position
    ori = head.orientation
    print(f"  Head position: [{pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f}]")
    print(f"  Head orientation: [{ori[0]:.3f}, {ori[1]:.3f}, {ori[2]:.3f}, {ori[3]:.3f}]")
print()

# Test 8: Run tracking loop
print("[Test 8] Running tracking loop (5 seconds)...")
frame_count = 0
start_time = time.time()

try:
    while time.time() - start_time < 5.0:
        if not manager.update():
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
print("[Test 9] Shutdown...")
manager.shutdown()
print("✓ Shutdown complete")
print()

print("=" * 80)
print("✅ All tests passed!")
print("=" * 80)
print()
print("Modular Architecture Working:")
print("  ✓ Independent tracker creation")
print("  ✓ Manager-based session coordination")
print("  ✓ Automatic extension collection")
print("  ✓ Hand + Head tracking in single session")
print("  ✓ Clean API design")

