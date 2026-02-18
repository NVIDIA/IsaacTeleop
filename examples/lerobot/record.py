# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Record a LeRobot dataset from head and hand tracking.

Demonstrates the modular architecture where you can:
- Create OpenXR session and add trackers
- Record tracking data to a LeRobot dataset with proper visualization support
"""

import sys
import time
import numpy as np
from pathlib import Path
import isaacteleop.deviceio as deviceio
import isaacteleop.oxr as oxr
import isaacteleop.schema as schema
from lerobot.datasets.lerobot_dataset import LeRobotDataset


def main():
    print("===========================================")
    print("OpenXR Tracking + LeRobot Dataset Recording")
    print("===========================================")
    print()

    # STEP 1: Define LeRobot dataset features
    print("Setting up LeRobot dataset...")
    features = {
        "observation.head": {
            "dtype": "float32",
            "shape": (3,),  # head_pos(3)
            "names": [
                # Head (3)
                "head_x",
                "head_y",
                "head_z",
            ],
        },
        "observation.left_hand": {
            "dtype": "float32",
            "shape": (3,),  # left_hand_pos(3)
            "names": [
                # Left hand (3)
                "left_hand_x",
                "left_hand_y",
                "left_hand_z",
            ],
        },
        "observation.right_hand": {
            "dtype": "float32",
            "shape": (3,),  # right_hand_pos(3)
            "names": [
                # Right hand (3)
                "right_hand_x",
                "right_hand_y",
                "right_hand_z",
            ],
        },
    }

    # STEP 2: Create LeRobot dataset
    # Use a timestamped directory so repeated runs create unique datasets
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    dataset_path = Path(__file__).parent / f"local_datasets/teleop_tracking_{timestamp}"
    dataset = LeRobotDataset.create(
        repo_id="teleop/tracking_demo",
        fps=60,  # ~60 FPS tracking
        features=features,
        root=dataset_path,
        use_videos=False,
    )
    print(f"Dataset created at: {dataset_path}")

    # Create trackers independently
    print("\nCreating trackers...")
    hand_tracker = deviceio.HandTracker()
    head_tracker = deviceio.HeadTracker()
    print(f"Created {hand_tracker.get_name()}")
    print(f"Created {head_tracker.get_name()}")
    trackers = [hand_tracker, head_tracker]

    # Get required extensions
    required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)

    # Create OpenXR session
    print("\nCreating OpenXR session...")
    with oxr.OpenXRSession("ModularExample", required_extensions) as oxr_session:
        handles = oxr_session.get_handles()
        print("OpenXR session created")

        # Create teleop session
        print("\nInitializing teleop session...")
        session = deviceio.DeviceIOSession.run(trackers, handles)

        with session:
            print("Teleop session initialized with all trackers!")
            print()

            # Main tracking loop
            print("===========================================")
            print("Tracking + Recording (60 seconds)...")
            print("===========================================")
            print()

            frame_count = 0
            start_time = time.time()

            try:
                while time.time() - start_time < 10.0:
                    # Update session and all trackers
                    if not session.update():
                        print("Update failed")
                        break

                    # Get hand data
                    left: schema.HandPoseT = hand_tracker.get_left_hand(session)
                    right: schema.HandPoseT = hand_tracker.get_right_hand(session)
                    head: schema.HeadPoseT = head_tracker.get_head(session)

                    # Extract positions and orientations (with defaults for invalid data)
                    left_pos = np.zeros(3, dtype=np.float32)
                    right_pos = np.zeros(3, dtype=np.float32)

                    if left.is_active and left.joints:
                        wrist = left.joints[deviceio.JOINT_WRIST]
                        if wrist.is_valid:
                            pos = wrist.pose.position
                            left_pos = np.array([pos.x, pos.y, pos.z], dtype=np.float32)

                    if right.is_active and right.joints:
                        wrist = right.joints[deviceio.JOINT_WRIST]
                        if wrist.is_valid:
                            pos = wrist.pose.position
                            right_pos = np.array(
                                [pos.x, pos.y, pos.z], dtype=np.float32
                            )

                    head_pos = np.zeros(3, dtype=np.float32)
                    if head.is_valid and head.pose:
                        pos = head.pose.position
                        head_pos = np.array([pos.x, pos.y, pos.z], dtype=np.float32)

                    # STEP 3: Record frame to dataset
                    observation_head = np.concatenate(
                        [
                            head_pos,  # head_pos(3)
                        ]
                    )

                    observation_left_hand = np.concatenate(
                        [
                            left_pos,  # left_hand_pos(3)
                        ]
                    )

                    observation_right_hand = np.concatenate(
                        [
                            right_pos,  # right_hand_pos(3)
                        ]
                    )

                    dataset.add_frame(
                        {
                            "task": "teleop_tracking",
                            "observation.head": observation_head,
                            "observation.left_hand": observation_left_hand,
                            "observation.right_hand": observation_right_hand,
                        }
                    )

                    # Print every 60 frames (~1 second)
                    if frame_count % 60 == 0:
                        elapsed = time.time() - start_time
                        print(f"[{elapsed:4.1f}s] Frame {frame_count} recorded")

                    frame_count += 1
                    time.sleep(0.016)  # ~60 FPS

            except KeyboardInterrupt:
                print("\nInterrupted by user")

            # STEP 4: Save episode
            print(f"\nSaving episode with {frame_count} frames...")
            dataset.save_episode()
            print("Episode saved")

            # Cleanup
            print(f"\nProcessed {frame_count} frames")
            print("Cleaning up (RAII)...")
            print("Resources will be cleaned up when exiting 'with' blocks")

    # STEP 5: Finalize dataset (creates stats.json)
    print("\nFinalizing dataset...")
    dataset.finalize()
    print("Dataset finalized")

    print("===========================================")
    print("Dataset Summary")
    print("===========================================")
    print(f"Dataset path: {dataset.root}")
    print(f"Total episodes: {dataset.meta.total_episodes}")
    print(f"Total frames: {dataset.meta.total_frames}")
    print(f"FPS: {dataset.fps}")
    print("===========================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())
