# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
OpenXR Modular Tracking Example with MCAP Recording

Demonstrates the modular architecture with MCAP data capture:
- Create independent trackers
- Add only the trackers you need
- Record all tracker data to an MCAP file for playback/analysis
- Pass mcap_filename and mcap_channels to DeviceIOSession.run() to enable recording
"""

import sys
import time
from datetime import datetime
import isaacteleop.deviceio as deviceio
import isaacteleop.oxr as oxr


def main():
    print("=" * 60)
    print("OpenXR Modular Tracking Example with MCAP Recording")
    print("=" * 60)
    print()

    # Generate timestamped filename for recording
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mcap_filename = f"tracking_recording_{timestamp}.mcap"

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
    with oxr.OpenXRSession(
        "ModularExampleWithMCAP", required_extensions
    ) as oxr_session:
        handles = oxr_session.get_handles()
        print("✓ OpenXR session created")

        # Run deviceio session with MCAP recording enabled.
        print("\nRunning deviceio session with MCAP recording...")
        recording_config = deviceio.McapRecordingConfig(
            mcap_filename, [(hand_tracker, "hands"), (head_tracker, "head")]
        )
        with deviceio.DeviceIOSession.run(
            trackers, handles, recording_config
        ) as session:
            print("✓ DeviceIO session initialized with all trackers!")
            print(f"✓ MCAP recording active → {mcap_filename}")
            print()

            # Main tracking loop
            print("=" * 60)
            print("Tracking (30 seconds)...")
            print("=" * 60)
            print()

            frame_count = 0
            start_time = time.time()

            while time.time() - start_time < 30.0:
                session.update(time.monotonic_ns())

                # Print every 60 frames (~1 second)
                if frame_count % 60 == 0:
                    elapsed = time.time() - start_time
                    print(f"[{elapsed:4.1f}s] Frame {frame_count} (recording...)")
                    print()

                frame_count += 1
                time.sleep(0.016)  # ~60 FPS

            print(f"\nProcessed {frame_count} frames")

        print("✓ Recording stopped (MCAP file closed by session destructor)")

    print()
    print("=" * 60)
    print(f"✓ Recording saved to: {mcap_filename}")
    print("  You can view this file with Foxglove Studio or mcap CLI")
    print("=" * 60)
    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
