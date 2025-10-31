#!/usr/bin/env python3
"""
OpenXR Modular Tracking Example

Demonstrates the new modular architecture where you can:
- Create independent trackers
- Add only the trackers you need
- Easily extend with new tracker types
"""

import sys
import time
import oxr_tracking


def main():
    print("=" * 60)
    print("OpenXR Modular Tracking Example")
    print("=" * 60)
    print()
    
    # Create trackers independently
    print("Creating trackers...")
    hand_tracker = oxr_tracking.HandTracker()
    head_tracker = oxr_tracking.HeadTracker()
    print(f"✓ Created {hand_tracker.get_name()}")
    print(f"✓ Created {head_tracker.get_name()}")
    
    # Create manager
    manager = oxr_tracking.OpenXRManager()
    
    # Add trackers (only add what you need!)
    print("\nAdding trackers to manager...")
    manager.add_tracker(hand_tracker)
    manager.add_tracker(head_tracker)
    print("✓ Trackers added")
    
    # Initialize (extensions are automatically collected from trackers)
    print("\nInitializing OpenXR...")
    if not manager.initialize("ModularExample"):
        print("❌ Failed to initialize")
        return 1
    
    print("✅ OpenXR initialized with all trackers!")
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
            # Update all trackers with one call
            if not manager.update():
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
                    wrist = left.get_joint(oxr_tracking.JOINT_WRIST)
                    if wrist.is_valid:
                        pos = wrist.position
                        print(f"    Left wrist: [{pos[0]:6.3f}, {pos[1]:6.3f}, {pos[2]:6.3f}]")
                
                # Get head data
                head = head_tracker.get_head()
                print(f"  Head: {'VALID' if head.is_valid else 'INVALID':8s}")
                
                if head.is_valid:
                    pos = head.position
                    print(f"    Head position: [{pos[0]:6.3f}, {pos[1]:6.3f}, {pos[2]:6.3f}]")
                
                print()
            
            frame_count += 1
            time.sleep(0.016)  # ~60 FPS
    
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    
    # Cleanup
    print(f"\nProcessed {frame_count} frames")
    print("Shutting down...")
    manager.shutdown()
    
    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())


