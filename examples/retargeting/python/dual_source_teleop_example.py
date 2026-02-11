#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Dual ControllersSource Teleop Example

Demonstrates using two ControllersSource nodes in a single TeleopSession pipeline.
This is a realistic scenario for bimanual control: one ControllersSource feeds the
left arm SE3 retargeter, another feeds the right arm SE3 retargeter.

KNOWN BUG: This example currently triggers a bug in TeleopSession where only the
first source's ControllerTracker is registered with DeviceIO (tracker deduplication
in __enter__), but the second source still tries to poll its own unregistered
tracker in _collect_tracker_data(). The second source will either crash or return
stale/uninitialized data.

Bug location:
  - teleop_session.py __enter__(): tracker_by_type.setdefault(type(tracker), tracker)
    keeps only the first tracker of each type
  - teleop_session.py _collect_tracker_data(): iterates ALL sources, each polls
    its OWN tracker -- the second source's tracker was never given to DeviceIO

Pipeline structure:
  ControllersSource("ctrl_left")  ──> Se3AbsRetargeter ──> "left_ee_pose"
  ControllersSource("ctrl_right") ──> Se3AbsRetargeter ──> "right_ee_pose"
                                                      └──> OutputCombiner
"""

import sys
import time
import numpy as np

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
)
from isaacteleop.retargeting_engine.retargeters import (
    Se3AbsRetargeter,
    Se3RetargeterConfig,
)
from isaacteleop.retargeting_engine.interface import OutputCombiner
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
)


def main() -> int:
    print("=" * 80)
    print("  Dual ControllersSource Teleop Example")
    print("=" * 80)
    print("Uses two ControllersSource nodes in a single pipeline.")
    print("Each source feeds one SE3 retargeter for bimanual arm control.")
    print("=" * 80 + "\n")

    # ==================================================================
    # Step 1: Create two separate ControllersSource nodes
    # ==================================================================
    # Each ControllersSource creates its own ControllerTracker internally.
    # BUG: TeleopSession deduplicates trackers by type, so only the first
    #       source's tracker will be registered with DeviceIO. The second
    #       source's tracker is orphaned.

    print("[Step 1] Creating two ControllersSource nodes...")
    ctrl_left_source = ControllersSource(name="ctrl_left")
    ctrl_right_source = ControllersSource(name="ctrl_right")
    print(f"  ✓ ControllersSource('ctrl_left')  - tracker id: {id(ctrl_left_source.get_tracker())}")
    print(f"  ✓ ControllersSource('ctrl_right') - tracker id: {id(ctrl_right_source.get_tracker())}")
    print(f"  ⚠ Both trackers are type: {type(ctrl_left_source.get_tracker()).__name__}")
    print(f"    Only one will survive deduplication in TeleopSession.__enter__()")

    # ==================================================================
    # Step 2: Build retargeting pipeline
    # ==================================================================
    # Left arm: controller_left from first source
    # Right arm: controller_right from second source

    print("\n[Step 2] Building retargeting pipeline...")

    # Left arm SE3 retargeter (using left controller from first source)
    left_se3_config = Se3RetargeterConfig(
        input_device=ControllersSource.LEFT,
        use_wrist_position=True,
        use_wrist_rotation=True,
        zero_out_xy_rotation=False,
    )
    left_se3 = Se3AbsRetargeter(left_se3_config, name="left_se3")
    connected_left = left_se3.connect({
        ControllersSource.LEFT: ctrl_left_source.output(ControllersSource.LEFT),
    })
    print("  ✓ Left SE3: ctrl_left_source.controller_left -> left_ee_pose")

    # Right arm SE3 retargeter (using right controller from second source)
    right_se3_config = Se3RetargeterConfig(
        input_device=ControllersSource.RIGHT,
        use_wrist_position=True,
        use_wrist_rotation=True,
        zero_out_xy_rotation=False,
    )
    right_se3 = Se3AbsRetargeter(right_se3_config, name="right_se3")
    connected_right = right_se3.connect({
        ControllersSource.RIGHT: ctrl_right_source.output(ControllersSource.RIGHT),
    })
    print("  ✓ Right SE3: ctrl_right_source.controller_right -> right_ee_pose")

    # ==================================================================
    # Step 3: Combine outputs
    # ==================================================================
    print("\n[Step 3] Combining outputs...")

    pipeline = OutputCombiner({
        "left_ee_pose": connected_left.output("ee_pose"),
        "right_ee_pose": connected_right.output("ee_pose"),
    })
    print("  ✓ Pipeline: 2 ControllersSource -> 2 Se3AbsRetargeter -> OutputCombiner")

    # ==================================================================
    # Step 4: Create and run TeleopSession
    # ==================================================================
    print("\n[Step 4] Creating TeleopSession...")

    session_config = TeleopSessionConfig(
        app_name="DualControllerSourceExample",
        trackers=[],  # Auto-discovered from pipeline sources
        pipeline=pipeline,
    )

    with TeleopSession(session_config) as session:
        print("  ✓ Session initialized")

        # Diagnostic: show which tracker survived deduplication
        print("\n  [Diagnostic] Discovered sources:")
        for source in session._sources:
            tracker = source.get_tracker()
            print(f"    - {source.name}: tracker id={id(tracker)}, type={type(tracker).__name__}")

        print("\n" + "=" * 80)
        print("  Running Bimanual Controller Teleop (20 seconds)")
        print("  Move left/right controllers to position arms")
        print("=" * 80 + "\n")

        start_time = time.time()
        duration = 20.0

        while time.time() - start_time < duration:
            # BUG: This will fail or produce incorrect results for the second source.
            # The second ControllersSource polls its own tracker, which was never
            # registered with DeviceIO (discarded during deduplication).
            result = session.step()

            left_pose = result["left_ee_pose"][0]
            right_pose = result["right_ee_pose"][0]

            if session.frame_count % 30 == 0:
                elapsed = session.get_elapsed_time()
                left_pos = left_pose[:3]
                right_pos = right_pose[:3]

                print(f"[{elapsed:5.1f}s] Frame {session.frame_count}")
                print(f"  Left  arm: ({left_pos[0]:+6.3f}, {left_pos[1]:+6.3f}, {left_pos[2]:+6.3f})")
                print(f"  Right arm: ({right_pos[0]:+6.3f}, {right_pos[1]:+6.3f}, {right_pos[2]:+6.3f})")

            time.sleep(0.016)

        fps = session.frame_count / duration
        print(f"\n  Done. Processed {session.frame_count} frames ({fps:.1f} FPS)")

    print("\n✅ Example completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
