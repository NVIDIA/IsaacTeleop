# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Writes a G4 label sidecar for a real recording, anchored to the clap in the data.

The clap is step 0 and exists as a sync event, which is what lets the prompter and the
recorder run without a common clock. Finding it as "the closest the hands ever come"
is not enough: the performer holds the controllers together while waiting, which is a
closer pass than some claps. The clap is instead the *last* hands-together event before
the first T-pose, since nothing between those two moments brings the hands together.

Every anchor is then checked against signals that do not depend on it -- a raised left
arm must actually be the left one -- because a misplaced anchor silently renames every
motion and the measurements downstream look plausible rather than wrong.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "checker" / "src"))

from full_body_acceptance.checks.geometry import FULL_BODY  # noqa: E402
from full_body_acceptance.mcap_source import McapFrameSource  # noqa: E402

from session import (  # noqa: E402
    CLAP_SEPARATION_M,
    STEPS,
    STILL_LABELS,
    TPOSE_SEPARATION_M,
)

J = {
    name: FULL_BODY.joint_names.index(name)
    for name in ("PELVIS", "LEFT_ANKLE", "RIGHT_ANKLE", "LEFT_HAND", "RIGHT_HAND")
}

NOTE = (
    "Out-of-band step labels. The in-recording annotation channel does not exist yet; "
    "these will migrate into the MCAP once it does."
)
CLOCK_DOMAIN = "sample_time_local_common_clock (system monotonic, nanoseconds)"


def read(recording: Path):
    """Returns per-frame (t_s, hand separation, hand y, ankle y, pelvis y)."""
    rows = []
    first_ns = None
    for frame in McapFrameSource(str(recording)):
        if not frame.has_payload or frame.sample_time_ns is None:
            continue
        joints = frame.joints
        if not all(joints[i].is_valid for i in J.values()):
            continue
        if first_ns is None:
            first_ns = frame.sample_time_ns
        left, right = joints[J["LEFT_HAND"]], joints[J["RIGHT_HAND"]]
        rows.append(
            {
                "t": (frame.sample_time_ns - first_ns) / 1e9,
                "sep": math.dist(left.position, right.position),
                "lh": left.position[1],
                "rh": right.position[1],
                "la": joints[J["LEFT_ANKLE"]].position[1],
                "ra": joints[J["RIGHT_ANKLE"]].position[1],
                "pelvis": joints[J["PELVIS"]].position[1],
            }
        )
    return rows, first_ns


CLAP_BURST_S = 1.5  # "clap twice" is two contacts; both belong to the one window


def find_clap(rows) -> float | None:
    tpose = next((r["t"] for r in rows if r["sep"] > TPOSE_SEPARATION_M), None)
    if tpose is None:
        return None
    together = [r["t"] for r in rows if r["t"] < tpose and r["sep"] < CLAP_SEPARATION_M]
    if not together:
        return None
    burst = [t for t in together if t >= together[-1] - CLAP_BURST_S]
    return (burst[0] + burst[-1]) / 2


def lay_out(clap_s: float, first_ns: int):
    steps = []
    at = clap_s - STEPS[0][1] / 2
    for index, (label, duration, _) in enumerate(STEPS):
        steps.append(
            {
                "index": index,
                "label": label,
                "start_ns": first_ns + round(at * 1e9),
                "end_ns": first_ns + round((at + duration) * 1e9),
                "start_s_from_first_sample": round(at, 6),
                "end_s_from_first_sample": round(at + duration, 6),
                "is_still_window": label in STILL_LABELS,
            }
        )
        at += duration
    return steps


def verify(steps, rows) -> list[tuple[str, bool, str]]:
    """Re-derives each window's motion from signals the anchor did not use."""
    standing = statistics.median([r["pelvis"] for r in rows])
    results = []
    for step in steps:
        a, b = step["start_s_from_first_sample"], step["end_s_from_first_sample"]
        window = [r for r in rows if a <= r["t"] < b]
        if not window:
            results.append((step["label"], False, "no frames in the window"))
            continue
        mean = lambda key: statistics.mean(r[key] for r in window)  # noqa: E731
        sep, lh, rh = mean("sep"), mean("lh"), mean("rh")
        la, ra = mean("la"), mean("ra")
        dip = standing - min(r["pelvis"] for r in window)
        label = step["label"]

        if label in ("t_pose_hold_open", "t_pose_hold_close"):
            results.append((label, sep > 1.30, f"hands {sep * 100:.0f} cm apart"))
        elif label == "left_arm_raise":
            results.append(
                (label, lh > rh + 0.25, f"left hand {lh:.2f} m vs right {rh:.2f} m")
            )
        elif label == "right_arm_raise":
            results.append(
                (label, rh > lh + 0.25, f"right hand {rh:.2f} m vs left {lh:.2f} m")
            )
        elif label == "left_leg_raise":
            results.append(
                (label, la > ra + 0.04, f"left ankle {la:+.3f} m vs right {ra:+.3f} m")
            )
        elif label == "right_leg_raise":
            results.append(
                (label, ra > la + 0.04, f"right ankle {ra:+.3f} m vs left {la:+.3f} m")
            )
        elif label == "squat_x2":
            results.append((label, dip > 0.15, f"pelvis drops {dip * 100:.0f} cm"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("recording", type=Path)
    parser.add_argument(
        "--clap-at",
        type=float,
        default=None,
        help="override the detected clap, seconds from first sample",
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    rows, first_ns = read(args.recording)
    if not rows:
        print(
            f"{args.recording.name}: no frames with all needed joints valid",
            file=sys.stderr,
        )
        return 1
    span = rows[-1]["t"]

    clap = args.clap_at if args.clap_at is not None else find_clap(rows)
    if clap is None:
        print(
            f"{args.recording.name}: no clap found "
            f"(hands never came within {CLAP_SEPARATION_M * 100:.0f} cm before a "
            f"T-pose, or there was no T-pose)",
            file=sys.stderr,
        )
        return 1

    steps = lay_out(clap, first_ns)
    checks = verify(steps, rows)
    ok = all(passed for _, passed, _ in checks)
    ends = steps[-1]["end_s_from_first_sample"]

    if not args.quiet:
        print(
            f"{args.recording.name}: {len(rows)} frames, {span:.1f} s, "
            f"clap at {clap:.2f} s"
        )
        for label, passed, detail in checks:
            print(f"    {'ok  ' if passed else 'BAD '} {label:<20} {detail}")
    if steps[0]["start_s_from_first_sample"] < 0:
        print("    BAD  script starts before the first sample")
        ok = False
    if ends > span:
        print(f"    BAD  script ends {ends - span:.1f} s past the last sample")
        ok = False

    payload = {
        "provisional": True,
        "note": NOTE,
        "clock_domain": CLOCK_DOMAIN,
        "nominal_rate_hz": round(len(rows) / span, 1) if span > 0 else None,
        "steps": steps,
        "mcap": args.recording.name,
    }
    sidecar = args.recording.with_name(args.recording.stem + ".labels.json")
    if args.write:
        sidecar.write_text(json.dumps(payload, indent=2) + "\n")
        print(
            f"    wrote {sidecar.name}  "
            f"({'anchor verified' if ok else 'ANCHOR SUSPECT'})"
        )
    else:
        print(f"    would write {sidecar.name}  (pass --write)")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
