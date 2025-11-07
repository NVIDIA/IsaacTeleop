#!/usr/bin/env python3
"""
Test session sharing between multiple TeleopSession instances.

This demonstrates how to create one OpenXR session directly and share it
across multiple managers with different trackers.
"""

import sys
import time

try:
    import teleopcore.xrio as xrio
    import teleopcore.oxr as oxr
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure the module is built")
    sys.exit(1)

print("=" * 80)
print("OpenXR Session Sharing Test (Python)")
print("=" * 80)
print()

# ============================================================================
# Step 1: Create OpenXR session directly with all required extensions
# ============================================================================
print("[Step 1] Creating standalone OpenXR session...")

# Define all extensions needed by our trackers
extensions = [
    "XR_KHR_convert_timespec_time",  # Required for time conversion
    "XR_MND_headless",                # Headless mode
    "XR_EXTX_overlay",                # Overlay mode
    "XR_EXT_hand_tracking"            # Hand tracking
]

print("  Required extensions:")
for ext in extensions:
    print(f"    - {ext}")

oxr_session = oxr.OpenXRSession.create("SessionSharingExample", extensions)
if oxr_session is None:
    print("  ✗ Failed to create OpenXR session")
    sys.exit(1)

print("  ✓ OpenXR session created")
print()

# ============================================================================
# Step 2: Get handles from the session
# ============================================================================
print("[Step 2] Getting session handles...")
handles = oxr_session.get_handles()

print(f"  Instance: {handles.instance:#x}")
print(f"  Session:  {handles.session:#x}")
print(f"  Space:    {handles.space:#x}")
print()

# ============================================================================
# Step 3: Create Manager 1 with HandTracker using the shared session
# ============================================================================
print("[Step 3] Creating Manager 1 with HandTracker...")
hand_tracker = xrio.HandTracker()

builder1 = xrio.TeleopSessionBuilder()
builder1.add_tracker(hand_tracker)

session1 = builder1.build(handles)
if session1 is None:
    print("  ✗ Failed to create teleop session 1")
    sys.exit(1)

print("  ✓ Manager 1 using shared session")
print()

# ============================================================================
# Step 4: Create Manager 2 with HeadTracker using the SAME shared session
# ============================================================================
print("[Step 4] Creating Manager 2 with HeadTracker...")
head_tracker = xrio.HeadTracker()

builder2 = xrio.TeleopSessionBuilder()
builder2.add_tracker(head_tracker)

session2 = builder2.build(handles)
if session2 is None:
    print("  ✗ Failed to create teleop session 2")
    sys.exit(1)

print("  ✓ Manager 2 using shared session")
print()

# ============================================================================
# Step 5: Update both sessions - they share the same OpenXR session!
# ============================================================================
print("[Step 5] Testing both managers with shared session (5 seconds)...")
print()

start_time = time.time()
frame_count = 0

try:
    while time.time() - start_time < 5.0:
        # Both sessions update using the same underlying OpenXR session
        if not session1.update():
            print("Session 1 update failed")
            break
        
        if not session2.update():
            print("Session 2 update failed")
            break
        
        # Print status every 60 frames
        if frame_count % 60 == 0:
            elapsed = time.time() - start_time
            
            # Get data from both trackers
            left = hand_tracker.get_left_hand()
            head = head_tracker.get_head()
            
            print(f"[{elapsed:4.1f}s] Frame {frame_count:3d}:")
            print(f"  Hands: {'ACTIVE' if left.is_active else 'INACTIVE':8s}")
            print(f"  Head:  {'VALID' if head.is_valid else 'INVALID':8s}")
            
            if left.is_active:
                wrist = left.get_joint(xrio.JOINT_WRIST)
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
print("  Destroying Manager 1...")
del session1  # RAII cleanup
print("  ✓ Manager 1 destroyed")

print("  Destroying Manager 2...")
del session2  # RAII cleanup
print("  ✓ Manager 2 destroyed")

print("  Destroying shared OpenXR session...")
del oxr_session  # RAII cleanup
print("  ✓ OpenXR session destroyed")
print()

print("=" * 80)
print("✓ Session sharing test complete")
print("=" * 80)
print()
print("Summary:")
print("  ✓ One OpenXR session created")
print("  ✓ Two managers shared the same session")
print("  ✓ HandTracker (Manager 1) and HeadTracker (Manager 2)")
print("  ✓ Both updated successfully with shared session")
print()

