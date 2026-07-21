#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Print live full-body frames published by noitom_mocap_plugin."""

from __future__ import annotations

import argparse
import time

import isaacteleop.deviceio as deviceio
import isaacteleop.oxr as oxr
from isaacteleop.schema import BodyJointPico


_JOINT_NAMES = (
    "pelvis",
    "left_hip",
    "right_hip",
    "spine1",
    "left_knee",
    "right_knee",
    "spine2",
    "left_ankle",
    "right_ankle",
    "spine3",
    "left_foot",
    "right_foot",
    "neck",
    "left_collar",
    "right_collar",
    "head",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hand",
    "right_hand",
)


def _format_point(point: object | None) -> str:
    if point is None:
        return "[n/a]"
    return f"[{point.x:+.3f}, {point.y:+.3f}, {point.z:+.3f}]"


def _joint(frame: object, index: int) -> object:
    return frame.joints.joints(index)


def _print_frame(
    frame: object,
    frame_index: int,
    elapsed_s: float,
    max_joints: int,
) -> None:
    joint_count = int(BodyJointPico.NUM_JOINTS)
    valid_joints = (
        0
        if frame.joints is None
        else sum(1 for index in range(joint_count) if _joint(frame, index).is_valid)
    )

    print(
        f"[{elapsed_s:6.2f}s] frame={frame_index:05d} "
        f"joints={valid_joints}/{joint_count} "
        f"all_joint_poses_tracked={frame.all_joint_poses_tracked}"
    )

    if frame.joints is None:
        return
    for index in range(min(max_joints, joint_count)):
        joint = _joint(frame, index)
        print(
            f"  joint {_JOINT_NAMES[index]:16s} valid={joint.is_valid} "
            f"pos={_format_point(joint.pose.position)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collection-id", default="noitom_mocap", help="OpenXR tensor collection id."
    )
    parser.add_argument("--max-flatbuffer-size", type=int, default=16 * 1024)
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Seconds to read. Use 0 for forever.",
    )
    parser.add_argument("--rate", type=float, default=60.0, help="Polling rate in Hz.")
    parser.add_argument(
        "--print-period", type=float, default=0.5, help="Seconds between status prints."
    )
    parser.add_argument("--max-joints", type=int, default=6)
    args = parser.parse_args()

    tracker = deviceio.FullBodyTrackerPico(args.collection_id, args.max_flatbuffer_size)
    required_extensions = deviceio.DeviceIOSession.get_required_extensions([tracker])

    print("Noitom full-body printer")
    print(f"  collection_id={args.collection_id}")
    print("  positions=meters")
    print(f"  required_extensions={required_extensions}")
    print("  start noitom_mocap_plugin before running this script")

    sleep_s = 0.0 if args.rate <= 0.0 else 1.0 / args.rate
    start_s = time.monotonic()
    last_print_s = 0.0
    frame_index = 0
    seen_frame = False

    with oxr.OpenXRSession("NoitomMocapPrinter", required_extensions) as oxr_session:
        handles = oxr_session.get_handles()
        with deviceio.DeviceIOSession.run([tracker], handles) as session:
            while args.duration <= 0.0 or time.monotonic() - start_s < args.duration:
                session.update()
                tracked = tracker.get_body_pose(session)
                frame = tracked.data
                elapsed_s = time.monotonic() - start_s

                if frame is None:
                    if elapsed_s - last_print_s >= args.print_period:
                        print(f"[{elapsed_s:6.2f}s] no Noitom frame yet")
                        last_print_s = elapsed_s
                elif elapsed_s - last_print_s >= args.print_period:
                    seen_frame = True
                    _print_frame(frame, frame_index, elapsed_s, args.max_joints)
                    last_print_s = elapsed_s

                frame_index += 1
                if sleep_s > 0.0:
                    time.sleep(sleep_s)

    if not seen_frame:
        print(
            "No frames received. Check that the plugin is running and the collection id matches."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
