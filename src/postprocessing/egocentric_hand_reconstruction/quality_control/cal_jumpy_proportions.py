#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Compute true/false proportions for jumpy-hand mask keys from a batch summary.

Reads qc_world_jumpy_batch_summary.json and reports, for each mask key:
  - With all videos: proportion of frames that are true vs false.
  - Excluding error videos: same proportions over only videos with error_video=false.

Useful frames/seconds: "useful" = frames where filtered_valid_mask is true.
  total_useful_frames = sum over videos of (num_frames - # frames where filtered_valid_mask is false).
  total_useful_seconds = total_useful_frames / fps (only when --fps is provided).

Usage:
  python quality_control/cal_jumpy_proportions.py --summary /path/to/qc_world_jumpy_batch_summary.json
  python quality_control/cal_jumpy_proportions.py --world_results_dir /path/to/folder [--fps 30]
  python quality_control/cal_jumpy_proportions.py --summary ... --out proportions.json --fps 30
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Any


def load_summary(path: Path) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def compute_proportions(
    videos: List[Dict],
    keys: List[str],
) -> Dict[str, Dict[str, float]]:
    """
    For each key, compute total_frames, total_true, total_false and proportions.
    Returns dict key -> {total_frames, total_true, total_false, proportion_true, proportion_false}.
    """
    out: Dict[str, Dict[str, float]] = {}
    for key in keys:
        total_frames = 0
        total_false = 0
        for v in videos:
            n = v.get("num_frames", 0)
            false_list = v.get("frames_false_by_key", {}).get(key, [])
            total_frames += n
            total_false += len(false_list)
        total_true = total_frames - total_false
        out[key] = {
            "total_frames": float(total_frames),
            "total_true": float(total_true),
            "total_false": float(total_false),
            "proportion_true": total_true / total_frames if total_frames else 0.0,
            "proportion_false": total_false / total_frames if total_frames else 0.0,
        }
    return out


def compute_useful_frames_and_seconds(
    videos: List[Dict],
    valid_key: str = "filtered_valid_mask",
    fps: float | None = None,
) -> Dict[str, float]:
    """
    Useful = frames where valid_key is true.
    Returns dict with total_frames, total_useful_frames, and optionally total_seconds, total_useful_seconds.
    """
    total_frames = 0
    total_useful_frames = 0
    for v in videos:
        n = v.get("num_frames", 0)
        false_list = v.get("frames_false_by_key", {}).get(valid_key, [])
        total_frames += n
        total_useful_frames += n - len(false_list)
    out: Dict[str, float] = {
        "total_frames": float(total_frames),
        "total_useful_frames": float(total_useful_frames),
    }
    if fps is not None and fps > 0:
        out["total_seconds"] = total_frames / fps
        out["total_useful_seconds"] = total_useful_frames / fps
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compute true/false proportions from jumpy batch summary."
    )
    ap.add_argument(
        "--summary",
        type=str,
        default=None,
        help="Path to qc_world_jumpy_batch_summary.json.",
    )
    ap.add_argument(
        "--world_results_dir",
        type=str,
        default=None,
        help="Folder containing qc_world_jumpy_batch_summary.json (summary path = <dir>/qc_world_jumpy_batch_summary.json).",
    )
    ap.add_argument(
        "--out",
        type=str,
        default=None,
        help="Optional path to write proportions JSON. If not set, only prints to stdout.",
    )
    ap.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Frames per second. If set, report total_useful_seconds and total_seconds (useful = filtered_valid_mask true).",
    )
    args = ap.parse_args()

    if args.summary is not None:
        summary_path = Path(args.summary).expanduser().resolve()
    elif args.world_results_dir is not None:
        summary_path = (
            Path(args.world_results_dir).expanduser().resolve()
            / "qc_world_jumpy_batch_summary.json"
        )
    else:
        ap.error("Provide either --summary or --world_results_dir.")

    if not summary_path.is_file():
        raise FileNotFoundError(f"Summary file not found: {summary_path}")

    data = load_summary(summary_path)
    videos: List[Dict] = data.get("videos", [])
    if not videos:
        print("No videos in summary.")
        return

    # Infer mask keys from first video's frames_false_by_key
    keys = sorted(videos[0].get("frames_false_by_key", {}).keys())
    if not keys:
        print("No mask keys in summary.")
        return

    all_videos = videos
    exclude_error = [v for v in videos if not v.get("error_video", False)]

    proportions_all = compute_proportions(all_videos, keys)
    proportions_exclude_error = (
        compute_proportions(exclude_error, keys)
        if exclude_error
        else {
            k: {
                "total_frames": 0.0,
                "total_true": 0.0,
                "total_false": 0.0,
                "proportion_true": 0.0,
                "proportion_false": 0.0,
            }
            for k in keys
        }
    )

    # Useful = frames where filtered_valid_mask is true
    useful_all = compute_useful_frames_and_seconds(
        all_videos, valid_key="filtered_valid_mask", fps=args.fps
    )
    useful_exclude_error = compute_useful_frames_and_seconds(
        exclude_error, valid_key="filtered_valid_mask", fps=args.fps
    )

    report = {
        "summary_path": str(summary_path),
        "num_videos_all": len(all_videos),
        "num_videos_excluding_error": len(exclude_error),
        "num_error_videos": len(all_videos) - len(exclude_error),
        "useful_frames_with_error_videos": useful_all,
        "useful_frames_excluding_error_videos": useful_exclude_error,
        "fps": args.fps,
        "proportions_with_error_videos": proportions_all,
        "proportions_excluding_error_videos": proportions_exclude_error,
    }

    # Print summary table
    print(f"Summary: {summary_path}")
    print(
        f"Videos: {len(all_videos)} total, {len(exclude_error)} excluding error, {len(all_videos) - len(exclude_error)} error"
    )
    print()
    print("Useful (filtered_valid_mask = true):")
    print(
        f"  With error videos:    {int(useful_all['total_useful_frames']):>10} useful frames / {int(useful_all['total_frames']):>10} total frames",
        end="",
    )
    if args.fps is not None and args.fps > 0:
        print(
            f"  ->  {useful_all['total_useful_seconds']:.2f} s useful / {useful_all['total_seconds']:.2f} s total (fps={args.fps})"
        )
    else:
        print()
    print(
        f"  Excl. error videos:  {int(useful_exclude_error['total_useful_frames']):>10} useful frames / {int(useful_exclude_error['total_frames']):>10} total frames",
        end="",
    )
    if args.fps is not None and args.fps > 0:
        print(
            f"  ->  {useful_exclude_error['total_useful_seconds']:.2f} s useful / {useful_exclude_error['total_seconds']:.2f} s total (fps={args.fps})"
        )
    else:
        print()
    if args.fps is None:
        print("  (Pass --fps to get useful seconds and total seconds.)")
    print()
    print("Proportions (with error videos):")
    print(f"  {'Mask key':<50} {'prop_true':>12} {'prop_false':>12}  total_frames")
    print("  " + "-" * 78)
    for key in keys:
        p = proportions_all[key]
        print(
            f"  {key:<50} {p['proportion_true']:>12.4f} {p['proportion_false']:>12.4f}  {int(p['total_frames']):>10}"
        )
    print()
    print("Proportions (excluding error videos):")
    print(f"  {'Mask key':<50} {'prop_true':>12} {'prop_false':>12}  total_frames")
    print("  " + "-" * 78)
    for key in keys:
        p = proportions_exclude_error[key]
        print(
            f"  {key:<50} {p['proportion_true']:>12.4f} {p['proportion_false']:>12.4f}  {int(p['total_frames']):>10}"
        )

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
