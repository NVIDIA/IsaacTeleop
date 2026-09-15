# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Derives a fully-passing session from a real capture by amplifying one deficiency.

The capture this was built for (145511) passes 36 of 37 checks: the squat is even to
4.0 deg, the labels verify, every envelope and geometry check is clean. It fails only
the arm raise, whose hands reach 36 deg above the shoulder against a gate of 60. So the
arm-raise windows are the only thing edited here, and inside them only the three joints
below the shoulder.

Everything that made the real capture worth having survives: the 20.8 s lead-in, the
56.3 Hz timing and its jitter, the clap, the solved forearms varying 68% of their
length, the subject's own left-right asymmetry, and every other window untouched.

What this proves and what it does not
-------------------------------------
It proves no check misfires on the shape of real data -- which is the failure mode that
produced five defects in one afternoon, all of them invisible to 83 generated fixtures.

It does not prove a person can reach the gate. That one reading is synthetic, and a
fixture that passes because it was made to pass is no evidence about human reach. Only
a real capture with the arms fully overhead settles that, and this file does not
substitute for one.

Amplification preserves the motion's shape rather than replacing it. The excursion
above each window's own resting elevation is scaled by a constant, so the arm still
starts at the side, rises on the subject's own timing, and comes back down; only the
peak moves. Positions and orientations rotate together about the shoulder, because
consistency.position_orientation_same_frame reads parent-local offsets against the
orientations and holds to 0.0% on the real capture -- moving one without the other
would break a check that currently passes on real evidence.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "fullbody" / "src"))
sys.path.insert(0, str(HERE.parent / "fullbody"))

from fullbody_acceptance.labels import StepTimeline  # noqa: E402
from fullbody_acceptance.mcap_source import McapFrameSource  # noqa: E402
from fullbody_acceptance.profile import FULL_BODY  # noqa: E402
from tests import synth  # noqa: E402

# The chain hanging off the shoulder. The shoulder itself stays: it is where the
# rotation is centred, and it belongs to the torso the subject really held.
BELOW_SHOULDER = ("ELBOW", "WRIST", "HAND")

WINDOWS = {"left_arm_raise": "LEFT", "right_arm_raise": "RIGHT"}

# Comfortably clear of the 60 deg gate without pinning the arm to vertical, which no
# subject reaches and which would read as a suspiciously exact number.
TARGET_ELEVATION_DEG = 70.0


def normalise(v):
    length = math.sqrt(sum(c * c for c in v))
    return [c / length for c in v] if length > 0 else None


def cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def elevation_deg(reach) -> float | None:
    unit = normalise(reach)
    if unit is None:
        return None
    return math.degrees(math.asin(max(-1.0, min(1.0, unit[1]))))


def rotate_about(axis, angle_rad, point, origin):
    """Rodrigues rotation of `point` about `axis` through `origin`."""
    v = [point[i] - origin[i] for i in range(3)]
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    cr = cross(axis, v)
    dot = sum(axis[i] * v[i] for i in range(3))
    return tuple(
        origin[i] + v[i] * c + cr[i] * s + axis[i] * dot * (1.0 - c) for i in range(3)
    )


def reach_of(frame, side: str):
    shoulder = frame.joints[FULL_BODY.index(f"{side}_SHOULDER")]
    hand = frame.joints[FULL_BODY.index(f"{side}_HAND")]
    if not (shoulder.is_valid and hand.is_valid):
        return None, None
    return shoulder, [hand.position[i] - shoulder.position[i] for i in range(3)]


def profile_of(frames, timeline, label, side):
    """The window's resting and peak elevation, which set the amplification."""
    step = timeline.one(label)
    values = []
    for frame in frames:
        if frame.sample_time_ns is None or not step.contains(frame.sample_time_ns):
            continue
        shoulder, reach = reach_of(frame, side)
        if reach is None:
            continue
        angle = elevation_deg(reach)
        if angle is not None:
            values.append(angle)
    if not values:
        return None
    return min(values), max(values)


def amplify(frame, side: str, gain: float, rest_deg: float):
    """Rotates the arm below the shoulder so its excursion above rest scales by gain."""
    shoulder, reach = reach_of(frame, side)
    if reach is None:
        return frame
    now = elevation_deg(reach)
    if now is None:
        return frame
    delta = math.radians((gain - 1.0) * (now - rest_deg))
    if abs(delta) < 1e-9:
        return frame

    # Rotate the reach toward vertical: the axis is perpendicular to the plane the
    # reach and the up direction span, so the arm sweeps in its own plane of motion.
    # Positive rotation about reach x up carries the reach toward up, since the
    # Rodrigues derivative there is axis x reach, the part of up perpendicular to it.
    axis = normalise(cross(reach, (0.0, 1.0, 0.0)))
    if axis is None:
        return frame
    turn = synth.unit_quaternion(delta, tuple(axis))

    joints = list(frame.joints)
    for part in BELOW_SHOULDER:
        index = FULL_BODY.index(f"{side}_{part}")
        pose = joints[index]
        if not pose.is_valid:
            continue
        joints[index] = dataclasses.replace(
            pose,
            position=rotate_about(axis, delta, pose.position, shoulder.position),
            orientation=synth.qmul(turn, pose.orientation),
        )
    return dataclasses.replace(frame, joints=tuple(joints))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("recording", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--target", type=float, default=TARGET_ELEVATION_DEG)
    args = parser.parse_args()

    timeline = StepTimeline.beside(args.recording)
    if timeline is None:
        print(f"{args.recording.name}: no label sidecar beside it", file=sys.stderr)
        return 1
    frames = list(McapFrameSource(str(args.recording)))

    plan = {}
    for label, side in WINDOWS.items():
        bounds = profile_of(frames, timeline, label, side)
        if bounds is None:
            print(f"{label}: no measurable frames", file=sys.stderr)
            return 1
        rest, peak = bounds
        if peak - rest < 1.0:
            print(f"{label}: the arm never moves, nothing to amplify", file=sys.stderr)
            return 1
        plan[label] = (side, rest, (args.target - rest) / (peak - rest))
        print(
            f"  {label:<17} rest {rest:6.1f}  peak {peak:6.1f}  -> gain {plan[label][2]:.2f}"
        )

    steps = {label: timeline.one(label) for label in WINDOWS}
    edited = []
    for frame in frames:
        for label, (side, rest, gain) in plan.items():
            step = steps[label]
            if frame.sample_time_ns is not None and step.contains(frame.sample_time_ns):
                frame = amplify(frame, side, gain, rest)
        edited.append(frame)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    synth.write_recording(args.out, edited)

    sidecar = args.recording.with_name(args.recording.stem + ".labels.json")
    if sidecar.is_file():
        target = args.out.with_name(args.out.stem + ".labels.json")
        shutil.copyfile(sidecar, target)
        payload = json.loads(target.read_text())
        payload["mcap"] = args.out.name
        payload["derived_from"] = args.recording.name
        payload["derivation"] = (
            "Arm-raise windows amplified about the shoulder to clear the range gate; "
            "every other window and joint is the original capture."
        )
        target.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"\n  wrote {args.out}  ({len(edited)} frames)")
    for label, (side, rest, _) in plan.items():
        after = profile_of(edited, timeline, label, side)
        print(f"  {label:<17} now peaks at {after[1]:.1f} deg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
