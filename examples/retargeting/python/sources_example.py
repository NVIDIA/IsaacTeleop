#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Retargeting Engine DeviceIO Sources Example

Demonstrates using the retargeting engine DeviceIO source modules.
Source modules are stateless converters that transform raw DeviceIO flatbuffer data
into the standard retargeting engine tensor format.

This example shows:
- Creating DeviceIO source modules (hand, head, controller)
- Source modules automatically create their own trackers
- Setting up OpenXR and DeviceIO sessions
- Manually polling DeviceIO trackers for raw data
- Passing raw data through source modules to convert to tensor format
- Using OutputCombiner to combine outputs from multiple sources
- Reading combined data in tensor format
- Printing tracking data in real-time
"""

import sys
import time
import isaacteleop.deviceio as deviceio
import isaacteleop.oxr as oxr
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    HandsSource,
    HeadSource,
    ControllersSource,
)
from isaacteleop.retargeting_engine.interface import OutputCombiner, TensorGroup


def main():
    print("=" * 70)
    print("Retargeting Engine DeviceIO Sources Example")
    print("=" * 70)
    print()

    # ========================================================================
    # Step 1: Create source modules (they create their own trackers)
    # ========================================================================
    print("[Step 1] Creating source modules...")
    hands_source = HandsSource(name="hands")
    head_source = HeadSource(name="head")
    controllers_source = ControllersSource(name="controllers")
    print("  ✓ Created HandsSource")
    print("  ✓ Created HeadSource")
    print("  ✓ Created ControllersSource")

    # ========================================================================
    # Step 2: Get trackers from sources and query required extensions
    # ========================================================================
    print("\n[Step 2] Getting trackers from sources...")
    hand_tracker = hands_source.get_tracker()
    head_tracker = head_source.get_tracker()
    controller_tracker = controllers_source.get_tracker()
    trackers = [hand_tracker, head_tracker, controller_tracker]
    print(f"  ✓ Got {len(trackers)} trackers from sources")

    print("\n[Step 3] Querying required OpenXR extensions...")
    required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
    print(f"  ✓ Required extensions: {', '.join(required_extensions)}")

    # ========================================================================
    # Step 3: Create OpenXR session
    # ========================================================================
    print("\n[Step 4] Creating OpenXR session...")
    with oxr.OpenXRSession(
        "RetargetingSourcesExample", required_extensions
    ) as oxr_session:
        handles = oxr_session.get_handles()
        print("  ✓ OpenXR session created successfully")

        # ====================================================================
        # Step 5: Run DeviceIO session
        # ====================================================================
        print("\n[Step 5] Initializing DeviceIO session...")
        with deviceio.DeviceIOSession.run(trackers, handles) as session:
            print("  ✓ DeviceIO session initialized with all trackers")

            # ================================================================
            # Step 6: Create OutputCombiner to combine all source outputs
            # ================================================================
            print("\n[Step 6] Creating OutputCombiner to combine all sources...")
            combiner = OutputCombiner(
                {
                    # Hand outputs
                    HandsSource.LEFT: hands_source.output(HandsSource.LEFT),
                    HandsSource.RIGHT: hands_source.output(HandsSource.RIGHT),
                    # Head output
                    "head": head_source.output("head"),
                    # Controller outputs
                    ControllersSource.LEFT: controllers_source.output(
                        ControllersSource.LEFT
                    ),
                    ControllersSource.RIGHT: controllers_source.output(
                        ControllersSource.RIGHT
                    ),
                }
            )
            print("  ✓ Created OutputCombiner with 5 combined outputs")

            # ================================================================
            # Step 7: Main tracking loop
            # ================================================================
            print("\n[Step 7] Starting main tracking loop...")
            print("=" * 70)
            print("Tracking Data (10 seconds)")
            print("=" * 70)
            print()

            frame_count = 0
            start_time = time.time()

            while time.time() - start_time < 10.0:
                # Update session and all trackers
                if not session.update():
                    print("Update failed")
                    break

                # Print every 60 frames (~1 second)
                if frame_count % 60 == 0:
                    elapsed = time.time() - start_time
                    print(f"[{elapsed:4.1f}s] Frame {frame_count}")
                    print("-" * 70)

                    # ====================================================
                    # Manually poll DeviceIO trackers for raw data
                    # ====================================================
                    hand_left_raw = hand_tracker.get_left_hand(session)
                    hand_right_raw = hand_tracker.get_right_hand(session)
                    head_raw = head_tracker.get_head(session)
                    controller_data_raw = controller_tracker.get_controller_data(
                        session
                    )

                    # ====================================================
                    # Wrap raw data in TensorGroups for source inputs
                    # ====================================================

                    # Prepare inputs for each source module
                    hands_inputs = {}
                    hands_input_spec = hands_source.input_spec()
                    for input_name, group_type in hands_input_spec.items():
                        tg = TensorGroup(group_type)
                        if "left" in input_name.lower():
                            tg[0] = hand_left_raw
                        elif "right" in input_name.lower():
                            tg[0] = hand_right_raw
                        hands_inputs[input_name] = tg

                    head_inputs = {}
                    head_input_spec = head_source.input_spec()
                    for input_name, group_type in head_input_spec.items():
                        tg = TensorGroup(group_type)
                        tg[0] = head_raw
                        head_inputs[input_name] = tg

                    controllers_inputs = {}
                    controllers_input_spec = controllers_source.input_spec()
                    for input_name, group_type in controllers_input_spec.items():
                        tg = TensorGroup(group_type)
                        if "left" in input_name.lower():
                            tg[0] = controller_data_raw.left_controller
                        elif "right" in input_name.lower():
                            tg[0] = controller_data_raw.right_controller
                        controllers_inputs[input_name] = tg

                    # ====================================================
                    # Pass wrapped data to combiner with correct structure
                    # ====================================================
                    all_data = combiner(
                        {
                            "hands": hands_inputs,
                            "head": head_inputs,
                            "controllers": controllers_inputs,
                        }
                    )

                    # Extract hand data (now in tensor format)
                    left_hand = all_data[HandsSource.LEFT]
                    left_positions = left_hand[0]  # (26, 3) array of joint positions
                    left_active = left_hand[4]  # is_active boolean

                    right_hand = all_data[HandsSource.RIGHT]
                    right_positions = right_hand[0]  # (26, 3) array of joint positions
                    right_active = right_hand[4]  # is_active boolean

                    print("  Hands:")
                    print(f"    Left:  {'ACTIVE' if left_active else 'INACTIVE'}")
                    if left_active:
                        wrist_idx = deviceio.JOINT_WRIST
                        wrist_pos = left_positions[wrist_idx]
                        print(
                            f"      Wrist: [{wrist_pos[0]:6.3f}, {wrist_pos[1]:6.3f}, {wrist_pos[2]:6.3f}]"
                        )

                    print(f"    Right: {'ACTIVE' if right_active else 'INACTIVE'}")
                    if right_active:
                        wrist_idx = deviceio.JOINT_WRIST
                        wrist_pos = right_positions[wrist_idx]
                        print(
                            f"      Wrist: [{wrist_pos[0]:6.3f}, {wrist_pos[1]:6.3f}, {wrist_pos[2]:6.3f}]"
                        )

                    # Extract head data
                    head = all_data["head"]
                    head_position = head[0]  # (3,) array [x, y, z]
                    head_valid = head[2]  # is_valid boolean

                    print("  Head:")
                    print(f"    Status: {'VALID' if head_valid else 'INVALID'}")
                    if head_valid:
                        print(
                            f"    Position: [{head_position[0]:6.3f}, {head_position[1]:6.3f}, {head_position[2]:6.3f}]"
                        )

                    # Extract controller data
                    left_ctrl = all_data[ControllersSource.LEFT]
                    left_ctrl_active = left_ctrl[11]  # is_active boolean
                    left_trigger = left_ctrl[10]  # trigger_value float

                    right_ctrl = all_data[ControllersSource.RIGHT]
                    right_ctrl_active = right_ctrl[11]  # is_active boolean
                    right_trigger = right_ctrl[10]  # trigger_value float

                    print("  Controllers:")
                    print(f"    Left:  {'ACTIVE' if left_ctrl_active else 'INACTIVE'}")
                    if left_ctrl_active:
                        print(f"      Trigger: {left_trigger:4.2f}")

                    print(f"    Right: {'ACTIVE' if right_ctrl_active else 'INACTIVE'}")
                    if right_ctrl_active:
                        print(f"      Trigger: {right_trigger:4.2f}")

                    print()

                frame_count += 1
                time.sleep(0.016)  # ~60 FPS

            # ================================================================
            # Cleanup
            # ================================================================
            print()
            print("=" * 70)
            print(f"Processed {frame_count} frames ({frame_count / 10.0:.1f} FPS)")
            print("=" * 70)
            print("\nCleaning up...")
            print("  ✓ Resources will be cleaned up automatically (RAII)")

    print("\n✅ Example completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
