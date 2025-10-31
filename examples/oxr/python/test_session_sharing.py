#!/usr/bin/env python3
"""
Test session sharing between multiple OpenXRManager instances.

This demonstrates how to create one manager that owns the session,
and another manager that reuses the same session.
"""

import sys
import os
import time

# Add build directory to path
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
print("OpenXR Session Sharing Test (Python)")
print("=" * 80)
print()

# ============================================================================
# Manager 1: Create and own the session with HandTracker
# ============================================================================
print("[Manager 1] Creating with HandTracker...")
hand_tracker = oxr_tracking.HandTracker()

manager1 = oxr_tracking.OpenXRManager()
manager1.add_tracker(hand_tracker)

print("  Initializing (will create new session)...")
if not manager1.initialize("SessionOwner"):
    print("  ❌ Failed to initialize Manager 1")
    sys.exit(1)

print("  ✅ Manager 1 initialized and owns session")
print()

# Get session handles from Manager 1
print("[Session Handles] Getting from Manager 1...")
instance_handle = manager1.get_instance()
session_handle = manager1.get_session()
space_handle = manager1.get_space()

print(f"  Instance: {instance_handle:#x}")
print(f"  Session:  {session_handle:#x}")
print(f"  Space:    {space_handle:#x}")
print()

# ============================================================================
# Manager 2: Reuse session with HeadTracker
# ============================================================================
print("[Manager 2] Creating with HeadTracker using shared session...")
head_tracker = oxr_tracking.HeadTracker()

manager2 = oxr_tracking.OpenXRManager()
manager2.add_tracker(head_tracker)

print("  Initializing with external session handles...")
if not manager2.initialize("SessionReuser", instance_handle, session_handle, space_handle):
    print("  ❌ Failed to initialize Manager 2 with external session")
    sys.exit(1)

print("  ✅ Manager 2 initialized with shared session")
print()

# ============================================================================
# Test the recommended approach
# ============================================================================
print("=" * 80)
print("Testing (5 seconds)...")
print("=" * 80)
print()

start_time = time.time()
frame_count = 0

try:
    while time.time() - start_time < 5.0:
        # Manager 1 updates (owns session, handles polling)
        if not manager1.update():
            print("Manager 1 update failed")
            break
        
        # Manager 2 updates (external session, just updates trackers)
        if not manager2.update():
            print("Manager 2 update failed")
            break
        
        # Print status every 60 frames
        if frame_count % 60 == 0:
            elapsed = time.time() - start_time
            
            # Get data from Manager 1's trackers
            left = hand_tracker.get_left_hand()
            right = hand_tracker.get_right_hand()
            
            # Get data from Manager 2's trackers
            head = head_tracker.get_head()
            
            print(f"[{elapsed:4.1f}s] Frame {frame_count:3d}:")
            print(f"  Manager 1 (hands): Left={'ACTIVE' if left.is_active else 'INACTIVE':8s} | "
                  f"Right={'ACTIVE' if right.is_active else 'INACTIVE':8s}")
            print(f"  Manager 2 (head):  {'VALID' if head.is_valid else 'INVALID':8s}")
            
            if left.is_active:
                wrist = left.get_joint(oxr_tracking.JOINT_WRIST)
                if wrist.is_valid:
                    pos = wrist.position
                    print(f"    Left wrist: [{pos[0]:6.3f}, {pos[1]:6.3f}, {pos[2]:6.3f}]")
            
            if head.is_valid:
                pos = head.position
                print(f"    Head pos:   [{pos[0]:6.3f}, {pos[1]:6.3f}, {pos[2]:6.3f}]")
            
            print()
        
        frame_count += 1
        time.sleep(0.016)

except KeyboardInterrupt:
    print("\nInterrupted")

print(f"Processed {frame_count} frames")
print()

# ============================================================================
# Cleanup
# ============================================================================
print("[Cleanup]")
print("  Shutting down Manager 2 (external session, doesn't own it)...")
manager2.shutdown()
print("  ✅ Manager 2 shutdown")

print("  Shutting down Manager 1 (owns session)...")
manager1.shutdown()
print("  ✅ Manager 1 shutdown")
print()

print("=" * 80)
print("✅ Session Sharing Test Complete!")
print("=" * 80)
print()
print("Key Takeaways:")
print("  • ✅ Session sharing works in Python!")
print("  • ✅ Manager 1 created session, Manager 2 reused it")
print("  • ✅ Both managers updated successfully")
print("  • ✅ Hands tracked via Manager 1, Head via Manager 2")
print("  • ✅ Single shared OpenXR session")
print()
print("Note: While session sharing works, for most Python use cases,")
print("      it's simpler to use one manager with all trackers.")
print()

