#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Detect the "jumpy" hand/track from a Dyn-HaMR `*_world_results.npz`.

We consider two independent jump signals (per track):
  - Translation jump: large adjacent-frame delta of `trans` (L2 norm).
  - Rotation jump: large adjacent-frame delta of `root_orient` (axis-angle), measured as
    the relative rotation angle between consecutive frames.

Outputs:
  - Prints a short report to stdout (selected track + stats).
  - Optionally writes JSON and a PNG plot.
  - Always writes qc_world_jumpy_per_frame_labels.json with per-frame mask arrays
    (*_mask: true = normal/detected, false = jump/lost). Includes *_jump_interpolate_mask
    for each jump mask: fills 10-frame gaps between two jump frames with false.
    Keys: left/right_hand_translation_mask, *_rotation_mask, *_detection_mask,
    *_translation_jump_interpolate_mask, *_rotation_jump_interpolate_mask,
    and valid_mask (true only when all other masks are true for that frame).
    Detection masks come from track_info.json (see --track_info).

Example (single file):
  python quality_control/detect_jumpy_hand_from_world_results.py \\
    --world_results outputs/logs/.../smooth_fit/ego_view_3_000300_world_results.npz \\
    --json --plot --out_dir .../qc_results --trans_factor 3.0 --rot_factor 3.0

Example (batch: only logs/video-custom/.../...-all-shot-0-0--1/smooth_fit/*_000300_world_results.npz):
  python quality_control/detect_jumpy_hand_from_world_results.py \\
    --world_results_dir /path/to/osmo_results \\
    --json --plot --trans_factor 20.0 --rot_factor 20.0
  (Outputs go to <each npz>.parent.parent / qc_results; use --out_subdir to change.)
  Also writes qc_world_jumpy_batch_summary.json in the folder: per-video listing of which frames have which mask keys false.)

Default thresholds are median * factor (per track): --trans_factor (default 20.0),
  --rot_factor (default 20.0). Or set absolute: --trans_abs_threshold, --rot_abs_threshold_deg.
  Batch error flags: --error_threshold_factor_trans, --error_threshold_factor_rot (default 10.0 each), --error_valid_ratio (default 0.3).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


def _nanstat(x: np.ndarray, stat: str) -> float:
    if stat == "median":
        return float(np.nanmedian(x))
    if stat == "mean":
        return float(np.nanmean(x))
    raise ValueError(f"Unknown stat '{stat}'. Expected 'median' or 'mean'.")


def _skew(k: np.ndarray) -> np.ndarray:
    """
    k: (N,3)
    returns: (N,3,3)
    """
    kx, ky, kz = k[:, 0], k[:, 1], k[:, 2]
    z = np.zeros_like(kx)
    K = np.stack(
        [
            np.stack([z, -kz, ky], axis=-1),
            np.stack([kz, z, -kx], axis=-1),
            np.stack([-ky, kx, z], axis=-1),
        ],
        axis=-2,
    )
    return K


def axis_angle_to_rotmat(aa: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """
    Convert axis-angle vectors to rotation matrices using Rodrigues formula.

    aa: (N,3) axis-angle in radians.
    returns: (N,3,3)
    """
    aa = np.asarray(aa, dtype=np.float64)
    if aa.ndim != 2 or aa.shape[1] != 3:
        raise ValueError(f"axis_angle_to_rotmat expects (N,3), got {aa.shape}")

    theta = np.linalg.norm(aa, axis=1)  # (N,)
    k = np.zeros_like(aa)
    mask = theta > eps
    k[mask] = aa[mask] / theta[mask, None]

    K = _skew(k)  # (N,3,3)
    K2 = np.einsum("nij,njk->nik", K, K)

    sin_t = np.sin(theta)[:, None, None]
    cos_t = np.cos(theta)[:, None, None]

    eye = np.eye(3, dtype=np.float64)[None, :, :]
    R = eye + sin_t * K + (1.0 - cos_t) * K2
    return R.astype(np.float32)


def adjacent_translation_delta(trans_bt3: np.ndarray) -> np.ndarray:
    """
    trans_bt3: (B,T,3)
    returns: d_bt (B,T) where d[:,0]=NaN and d[:,t]=||trans[t]-trans[t-1]|| for t>=1
    """
    trans = np.asarray(trans_bt3, dtype=np.float32)
    if trans.ndim != 3 or trans.shape[-1] != 3:
        raise ValueError(f"Expected trans (B,T,3), got {trans.shape}")
    d = np.full(trans.shape[:2], np.nan, dtype=np.float32)
    dt = trans[:, 1:, :] - trans[:, :-1, :]
    d[:, 1:] = np.linalg.norm(dt, axis=-1)
    return d


def adjacent_rotation_angle_delta(root_orient_bt3: np.ndarray) -> np.ndarray:
    """
    root_orient_bt3: (B,T,3) axis-angle (radians)
    returns: ang_bt (B,T) where ang[:,0]=NaN and ang[:,t]=angle(R_{t-1}^T R_t) for t>=1 (radians)
    """
    aa = np.asarray(root_orient_bt3, dtype=np.float32)
    if aa.ndim != 3 or aa.shape[-1] != 3:
        raise ValueError(f"Expected root_orient (B,T,3), got {aa.shape}")
    B, T, _ = aa.shape
    ang = np.full((B, T), np.nan, dtype=np.float32)

    R = axis_angle_to_rotmat(aa.reshape(-1, 3)).reshape(B, T, 3, 3)  # (B,T,3,3)
    R_prev = R[:, :-1, :, :]
    R_cur = R[:, 1:, :, :]
    R_prev_T = np.transpose(R_prev, (0, 1, 3, 2))
    R_delta = np.einsum("btij,btjk->btik", R_prev_T, R_cur)  # (B,T-1,3,3)
    tr = R_delta[..., 0, 0] + R_delta[..., 1, 1] + R_delta[..., 2, 2]
    cosang = (tr - 1.0) * 0.5
    cosang = np.clip(cosang, -1.0, 1.0)
    ang[:, 1:] = np.arccos(cosang).astype(np.float32)
    return ang


def _is_right_from_is_right_bt(
    is_right_bt: Optional[np.ndarray], b: int
) -> Optional[bool]:
    if is_right_bt is None:
        return None
    x = float(np.asarray(is_right_bt)[b, 0])
    # Most logs store 0/1. Some codebases store track id; for B=2, this still works.
    return bool(x > 0.5)


@dataclass
class TrackJumpStats:
    track_index: int
    is_right: Optional[bool]
    trans_base: Optional[float]
    trans_thr: Optional[float]
    trans_jump_count: int
    trans_jump_frames: List[int]
    trans_max: Optional[float]
    rot_base: Optional[float]
    rot_thr: Optional[float]
    rot_jump_count: int
    rot_jump_frames: List[int]
    rot_max_rad: Optional[float]
    rot_max_deg: Optional[float]
    score: float


def _frames_where_over(d: np.ndarray, thr: float) -> List[int]:
    if not np.isfinite(thr):
        return []
    idx = np.where(np.isfinite(d) & (d > float(thr)))[0]
    return [int(i) for i in idx.tolist()]


def detect_jumpy_tracks(
    trans_bt3: np.ndarray,
    root_orient_bt3: np.ndarray,
    is_right_bt: Optional[np.ndarray],
    *,
    trans_stat: str,
    trans_factor: float,
    trans_abs_threshold: Optional[float],
    rot_stat: str,
    rot_factor: float,
    rot_abs_threshold_deg: Optional[float],
) -> Tuple[List[TrackJumpStats], int]:
    dtrans_bt = adjacent_translation_delta(trans_bt3)  # (B,T)
    drot_bt = adjacent_rotation_angle_delta(root_orient_bt3)  # (B,T) radians
    B = dtrans_bt.shape[0]

    out: List[TrackJumpStats] = []
    for b in range(B):
        dtrans = dtrans_bt[b]
        drot = drot_bt[b]

        # Translation threshold
        trans_base = None
        if trans_abs_threshold is None:
            if np.any(np.isfinite(dtrans)):
                trans_base = _nanstat(dtrans, trans_stat)
            trans_thr = (
                None if trans_base is None else float(trans_base) * float(trans_factor)
            )
        else:
            trans_thr = float(trans_abs_threshold)

        # Rotation threshold (convert degrees -> radians for internal compare)
        rot_base = None
        if rot_abs_threshold_deg is None:
            if np.any(np.isfinite(drot)):
                rot_base = _nanstat(drot, rot_stat)
            rot_thr_rad = (
                None if rot_base is None else float(rot_base) * float(rot_factor)
            )
        else:
            rot_thr_rad = math.radians(float(rot_abs_threshold_deg))

        trans_frames = (
            _frames_where_over(dtrans, trans_thr) if trans_thr is not None else []
        )
        rot_frames = (
            _frames_where_over(drot, rot_thr_rad) if rot_thr_rad is not None else []
        )

        trans_max = float(np.nanmax(dtrans)) if np.any(np.isfinite(dtrans)) else None
        rot_max_rad = float(np.nanmax(drot)) if np.any(np.isfinite(drot)) else None
        rot_max_deg = None if rot_max_rad is None else float(np.degrees(rot_max_rad))

        # Simple combined score: counts + a small tie-breaker on max magnitude.
        score = float(len(trans_frames) + len(rot_frames))
        if trans_max is not None:
            score += 1e-3 * float(trans_max)
        if rot_max_deg is not None:
            score += 1e-3 * float(rot_max_deg)

        out.append(
            TrackJumpStats(
                track_index=b,
                is_right=_is_right_from_is_right_bt(is_right_bt, b),
                trans_base=trans_base if trans_abs_threshold is None else None,
                trans_thr=trans_thr,
                trans_jump_count=len(trans_frames),
                trans_jump_frames=trans_frames,
                trans_max=trans_max,
                rot_base=rot_base if rot_abs_threshold_deg is None else None,
                rot_thr=None if rot_thr_rad is None else float(rot_thr_rad),
                rot_jump_count=len(rot_frames),
                rot_jump_frames=rot_frames,
                rot_max_rad=rot_max_rad,
                rot_max_deg=rot_max_deg,
                score=score,
            )
        )

    # Choose best track by score (deterministic tie-breakers embedded in score).
    best = int(np.argmax([t.score for t in out])) if len(out) else -1
    return out, best


def _maybe_plot(
    out_dir: Path,
    dtrans_bt: np.ndarray,
    drot_bt: np.ndarray,
    stats: List[TrackJumpStats],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    B, T = dtrans_bt.shape
    x = np.arange(T, dtype=np.int32)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 10), sharex=True)
    for b in range(B):
        label = f"track {b}"
        if stats[b].is_right is not None:
            label += " (right)" if stats[b].is_right else " (left)"
        (line1,) = ax1.plot(x, dtrans_bt[b], linewidth=1.2, alpha=0.85, label=label)
        color = line1.get_color()
        ax2.plot(
            x,
            np.degrees(drot_bt[b]),
            linewidth=1.2,
            alpha=0.85,
            label=label,
            color=color,
        )

        if stats[b].trans_thr is not None:
            ax1.axhline(
                float(stats[b].trans_thr),
                linestyle="--",
                linewidth=1.0,
                alpha=0.35,
                color=color,
            )
        if stats[b].rot_thr is not None:
            ax2.axhline(
                float(np.degrees(stats[b].rot_thr)),
                linestyle="--",
                linewidth=1.0,
                alpha=0.35,
                color=color,
            )

        # Mark the frames that were actually counted as "jumps"
        t_idx = np.asarray(stats[b].trans_jump_frames, dtype=np.int32)
        if t_idx.size > 0:
            ax1.scatter(
                t_idx,
                dtrans_bt[b, t_idx],
                s=14,
                color=color,
                alpha=0.75,
                edgecolors="none",
                marker="o",
            )
        r_idx = np.asarray(stats[b].rot_jump_frames, dtype=np.int32)
        if r_idx.size > 0:
            ax2.scatter(
                r_idx,
                np.degrees(drot_bt[b, r_idx]),
                s=14,
                color=color,
                alpha=0.75,
                edgecolors="none",
                marker="o",
            )

    ax1.set_title("Adjacent-frame translation delta ||trans[t]-trans[t-1]||")
    ax1.set_ylabel("Distance (world units)")
    ax1.grid(True, alpha=0.25)
    ax1.legend(loc="upper right", ncol=2)

    ax2.set_title(
        "Adjacent-frame rotation delta angle(root_orient[t-1]^T * root_orient[t])"
    )
    ax2.set_xlabel("Frame index t (delta is from t-1 → t)")
    ax2.set_ylabel("Angle (degrees)")
    ax2.grid(True, alpha=0.25)

    fig.tight_layout()
    out_path = out_dir / "qc_world_jumpy_deltas.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved plot: {out_path}")


def _load_track_info_detection_lost(
    track_info_path: Path, num_frames: int, stats: List[TrackJumpStats]
) -> Tuple[List[bool], List[bool]]:
    """
    Load track_info.json and return per-frame left_hand_detection_lost, right_hand_detection_lost.
    track_info tracks are keyed by track_id; track_id 0 = left, track_id 1 = right (per dataset convention).
    Uses meta.seq_interval [start, end) when present: NPZ frame t maps to vis_mask[seq_start + t], so the
    sequence length is seq_end - seq_start (should match num_frames). If seq_interval is missing, uses
    the first num_frames of vis_mask (legacy behavior).
    Returns (left_lost, right_lost), each of length num_frames. If a hand has no track, all True (lost).
    """
    left_lost = [True] * num_frames
    right_lost = [True] * num_frames
    if not track_info_path.is_file():
        return left_lost, right_lost

    with open(track_info_path, "r") as f:
        track_info = json.load(f)
    tracks = track_info.get("tracks", {})
    meta = track_info.get("meta", {})
    seq_interval = meta.get("seq_interval")  # [start, end) in original frame indices
    if seq_interval is not None and len(seq_interval) >= 2:
        seq_start, seq_end = int(seq_interval[0]), int(seq_interval[1])
    else:
        seq_start, seq_end = 0, None  # legacy: use vis_mask from index 0

    # Map track index (from world_results) to left/right using stats
    for b, s in enumerate(stats):
        # Find vis_mask for this track: track_info has track_id -> {index, vis_mask}; index matches our b
        vis_mask = None
        for tid, info in tracks.items():
            if info.get("index") == b:
                vis_mask = info.get("vis_mask")
                break
        if vis_mask is None:
            continue
        L = len(vis_mask)
        if seq_end is not None:
            # Slice vis_mask by seq_interval: NPZ frame t -> vis_mask[seq_start + t]
            start = seq_start
            end = min(seq_start + num_frames, L)
            n = end - start
            lost = [not bool(vis_mask[start + t]) for t in range(n)]
            if n < num_frames:
                lost += [True] * (num_frames - n)
        else:
            # Legacy: first num_frames of vis_mask
            n = min(L, num_frames)
            lost = [not bool(vis_mask[t]) for t in range(n)]
            if n < num_frames:
                lost += [True] * (num_frames - n)
        if s.is_right is False:
            left_lost = lost
        elif s.is_right is True:
            right_lost = lost
    return left_lost, right_lost


def _jump_interpolate_mask(mask: List[bool], window: int = 10) -> List[bool]:
    """
    For a jump mask (true=normal, false=jump): if frame t is a jump and any of the
    following `window` frames is also a jump at t', set all frames from t to t'
    (inclusive) to false in the result. Fills short gaps between nearby jumps.
    """
    T = len(mask)
    out = list(mask)
    for t in range(T):
        if mask[t]:
            continue
        for k in range(1, min(window + 1, T - t)):
            if not mask[t + k]:
                for i in range(t, t + k + 1):
                    out[i] = False
                break
    return out


def _filter_single_false(mask: List[bool], window: int = 10) -> List[bool]:
    """
    Return a copy of mask where a single false is turned true if the previous
    and following `window` frames are all true (isolated single-frame false).
    """
    T = len(mask)
    out = list(mask)
    for t in range(T):
        if mask[t]:
            continue
        prev_ok = t >= window and all(mask[i] for i in range(t - window, t))
        next_ok = t + window < T and all(mask[i] for i in range(t + 1, t + window + 1))
        if prev_ok and next_ok:
            out[t] = True
    return out


def build_per_frame_labels(
    stats: List[TrackJumpStats],
    num_frames: int,
    left_detection_lost: List[bool],
    right_detection_lost: List[bool],
) -> Dict[str, List[bool]]:
    """Build per-frame mask arrays: true = normal/detected, false = jump/lost."""
    left_trans: set = set()
    right_trans: set = set()
    left_rot: set = set()
    right_rot: set = set()
    for s in stats:
        # False = left, True = right; when is_right is None, assume track 0 = left, track 1 = right
        is_left = (s.is_right is False) or (s.is_right is None and s.track_index == 0)
        if is_left:
            left_trans.update(s.trans_jump_frames)
            left_rot.update(s.rot_jump_frames)
        else:
            right_trans.update(s.trans_jump_frames)
            right_rot.update(s.rot_jump_frames)

    # Masks: true = normal/detected, false = jump/lost
    left_trans_mask = [t not in left_trans for t in range(num_frames)]
    left_rot_mask = [t not in left_rot for t in range(num_frames)]
    right_trans_mask = [t not in right_trans for t in range(num_frames)]
    right_rot_mask = [t not in right_rot for t in range(num_frames)]
    left_trans_interp = _jump_interpolate_mask(left_trans_mask)
    left_rot_interp = _jump_interpolate_mask(left_rot_mask)
    right_trans_interp = _jump_interpolate_mask(right_trans_mask)
    right_rot_interp = _jump_interpolate_mask(right_rot_mask)
    left_det_mask = [not lost for lost in left_detection_lost]
    right_det_mask = [not lost for lost in right_detection_lost]

    all_masks = (
        left_trans_mask,
        left_rot_mask,
        right_trans_mask,
        right_rot_mask,
        left_trans_interp,
        left_rot_interp,
        right_trans_interp,
        right_rot_interp,
        left_det_mask,
        right_det_mask,
    )
    valid_mask = [all(m[t] for m in all_masks) for t in range(num_frames)]
    filtered_valid_mask = _filter_single_false(valid_mask)

    return {
        "left_hand_translation_mask": left_trans_mask,
        "left_hand_rotation_mask": left_rot_mask,
        "right_hand_translation_mask": right_trans_mask,
        "right_hand_rotation_mask": right_rot_mask,
        "left_hand_translation_jump_interpolate_mask": left_trans_interp,
        "left_hand_rotation_jump_interpolate_mask": left_rot_interp,
        "right_hand_translation_jump_interpolate_mask": right_trans_interp,
        "right_hand_rotation_jump_interpolate_mask": right_rot_interp,
        "left_hand_detection_mask": left_det_mask,
        "right_hand_detection_mask": right_det_mask,
        "valid_mask": valid_mask,
        "filtered_valid_mask": filtered_valid_mask,
    }


def _summary_frames_false_by_key(
    per_frame: Dict[str, List[bool]],
) -> Dict[str, List[int]]:
    """For each mask key, list frame indices where the value is false."""
    return {
        key: [t for t, v in enumerate(arr) if not v] for key, arr in per_frame.items()
    }


def _threshold_info_from_stats(
    stats: List[TrackJumpStats],
) -> Dict[str, Optional[float]]:
    """Extract max trans_thr and max rot_thr_deg across tracks for batch median/error check."""
    trans_vals = [s.trans_thr for s in stats if s.trans_thr is not None]
    rot_vals = [np.degrees(s.rot_thr) for s in stats if s.rot_thr is not None]
    return {
        "trans_thr": max(trans_vals) if trans_vals else None,
        "rot_thr_deg": max(rot_vals) if rot_vals else None,
    }


def process_one(
    world_results: Path,
    out_dir: Path,
    args: argparse.Namespace,
) -> Optional[Tuple[Dict[str, List[bool]], Dict[str, Optional[float]]]]:
    """Run jumpy-hand detection for a single world_results NPZ. Returns (per_frame, threshold_info) or None if no tracks."""
    d = np.load(world_results, allow_pickle=True)
    required = ["trans", "root_orient"]
    for k in required:
        if k not in d:
            raise KeyError(
                f"Missing key '{k}' in {world_results}. Found keys: {list(d.keys())}"
            )

    trans = d["trans"]  # (B,T,3)
    root_orient = d["root_orient"]  # (B,T,3) axis-angle
    is_right = d["is_right"] if "is_right" in d else None  # (B,T) or None

    stats, best = detect_jumpy_tracks(
        trans_bt3=trans,
        root_orient_bt3=root_orient,
        is_right_bt=is_right,
        trans_stat=args.trans_stat,
        trans_factor=float(args.trans_factor),
        trans_abs_threshold=args.trans_abs_threshold,
        rot_stat=args.rot_stat,
        rot_factor=float(args.rot_factor),
        rot_abs_threshold_deg=args.rot_abs_threshold_deg,
    )

    if len(stats) == 0 or best < 0:
        print(f"[{world_results}] No tracks found.")
        return None
    threshold_info = _threshold_info_from_stats(stats)

    print(f"Loaded: {world_results}")
    print(f"Tracks (B)={trans.shape[0]}, Frames (T)={trans.shape[1]}")
    print()

    for s in stats:
        side = None
        if s.is_right is not None:
            side = "right" if s.is_right else "left"
        trans_thr_str = "None" if s.trans_thr is None else f"{s.trans_thr:.6g}"
        rot_thr_deg_str = (
            "None" if s.rot_thr is None else f"{np.degrees(s.rot_thr):.3f}°"
        )
        print(
            f"- track {s.track_index}"
            + (f" ({side})" if side is not None else "")
            + f": score={s.score:.3f} | "
            + f"trans jumps={s.trans_jump_count} thr={trans_thr_str} max={s.trans_max if s.trans_max is not None else 'None'} | "
            + f"rot jumps={s.rot_jump_count} thr={rot_thr_deg_str} max={s.rot_max_deg if s.rot_max_deg is not None else 'None'}°"
        )

    chosen = stats[best]
    side = None if chosen.is_right is None else ("right" if chosen.is_right else "left")
    print()
    print(
        f"Selected jumpy track: {chosen.track_index}" + (f" ({side})" if side else "")
    )
    print(f"  trans_jump_frames (first 30): {chosen.trans_jump_frames[:30]}")
    print(f"  rot_jump_frames   (first 30): {chosen.rot_jump_frames[:30]}")

    # Optional outputs
    report: Dict = {
        "world_results": str(world_results),
        "selected_track_index": int(chosen.track_index),
        "selected_is_right": None if chosen.is_right is None else bool(chosen.is_right),
        "tracks": [
            {
                "track_index": int(s.track_index),
                "is_right": None if s.is_right is None else bool(s.is_right),
                "score": float(s.score),
                "translation": {
                    "base": None if s.trans_base is None else float(s.trans_base),
                    "threshold": None if s.trans_thr is None else float(s.trans_thr),
                    "jump_count": int(s.trans_jump_count),
                    "jump_frames": [int(i) for i in s.trans_jump_frames],
                    "max": None if s.trans_max is None else float(s.trans_max),
                },
                "rotation": {
                    "base_rad": None if s.rot_base is None else float(s.rot_base),
                    "threshold_rad": None if s.rot_thr is None else float(s.rot_thr),
                    "threshold_deg": None
                    if s.rot_thr is None
                    else float(np.degrees(s.rot_thr)),
                    "jump_count": int(s.rot_jump_count),
                    "jump_frames": [int(i) for i in s.rot_jump_frames],
                    "max_rad": None if s.rot_max_rad is None else float(s.rot_max_rad),
                    "max_deg": None if s.rot_max_deg is None else float(s.rot_max_deg),
                },
            }
            for s in stats
        ],
        "params": {
            "trans_stat": args.trans_stat,
            "trans_factor": float(args.trans_factor),
            "trans_abs_threshold": args.trans_abs_threshold,
            "rot_stat": args.rot_stat,
            "rot_factor": float(args.rot_factor),
            "rot_abs_threshold_deg": args.rot_abs_threshold_deg,
        },
    }

    if args.json:
        json_path = out_dir / "qc_world_jumpy_hand.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Saved JSON: {json_path}")

    # Per-frame labels (always written when we have stats)
    T = trans.shape[1]
    track_info_path = (
        Path(args.track_info).expanduser().resolve()
        if args.track_info
        else world_results.parent.parent / "track_info.json"
    )
    left_detection_lost, right_detection_lost = _load_track_info_detection_lost(
        track_info_path, T, stats
    )
    per_frame = build_per_frame_labels(
        stats, T, left_detection_lost, right_detection_lost
    )
    labels_path = out_dir / "qc_world_jumpy_per_frame_labels.json"
    with open(labels_path, "w") as f:
        json.dump(per_frame, f, indent=2)
    print(f"Saved per-frame labels: {labels_path}")

    if args.plot:
        dtrans_bt = adjacent_translation_delta(trans)
        drot_bt = adjacent_rotation_angle_delta(root_orient)
        _maybe_plot(out_dir, dtrans_bt, drot_bt, stats)

    return (per_frame, threshold_info)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--world_results",
        type=str,
        default=None,
        help="Path to a single Dyn-HaMR `*_world_results.npz` (required if --world_results_dir not set).",
    )
    ap.add_argument(
        "--world_results_dir",
        type=str,
        default=None,
        help="Directory to search for logs/video-custom/.../...-all-shot-0-0--1/smooth_fit/*_000300_world_results.npz; processes each (mutually exclusive with single file).",
    )
    ap.add_argument(
        "--out_subdir",
        type=str,
        default="qc_results",
        help="When using --world_results_dir, output for each NPZ is written to <npz>.parent.parent / out_subdir (default: qc_results).",
    )
    ap.add_argument(
        "--out_dir",
        type=str,
        default=None,
        help="Output directory for single-file mode (default: alongside the NPZ).",
    )
    ap.add_argument(
        "--track_info",
        type=str,
        default=None,
        help="Path to track_info.json (default: <world_results>.parent.parent / track_info.json).",
    )
    ap.add_argument("--json", action="store_true", help="If set, write a JSON report.")
    ap.add_argument(
        "--plot", action="store_true", help="If set, write a PNG plot of deltas."
    )

    ap.add_argument(
        "--trans_stat", type=str, default="median", choices=["median", "mean"]
    )
    ap.add_argument(
        "--trans_factor",
        type=float,
        default=20.0,
        help="Effective trans thr = stat(dtrans) * factor.",
    )
    ap.add_argument(
        "--trans_abs_threshold",
        type=float,
        default=None,
        help="Absolute translation jump threshold (overrides stat*factor). Units are the same as `trans` in NPZ.",
    )

    ap.add_argument(
        "--rot_stat", type=str, default="median", choices=["median", "mean"]
    )
    ap.add_argument(
        "--rot_factor",
        type=float,
        default=20.0,
        help="Effective rot thr = stat(drot_rad) * factor.",
    )
    ap.add_argument(
        "--rot_abs_threshold_deg",
        type=float,
        default=None,
        help="Absolute rotation jump threshold in degrees (overrides stat*factor).",
    )
    ap.add_argument(
        "--error_threshold_factor_trans",
        type=float,
        default=10.0,
        help="In batch mode: flag video as error_video if trans_thr > median_trans * this factor (default 10.0).",
    )
    ap.add_argument(
        "--error_threshold_factor_rot",
        type=float,
        default=10.0,
        help="In batch mode: flag video as error_video if rot_thr_deg > median_rot_deg * this factor (default 10.0).",
    )
    ap.add_argument(
        "--error_valid_ratio",
        type=float,
        default=0.3,
        help="In batch mode: also flag as error_video if filtered_invalid_ratio > this (default 0.3, i.e. >30%% invalid frames).",
    )

    args = ap.parse_args()

    if args.world_results_dir is not None:
        # Batch mode: only logs/video-custom/xxx/xxx-all-shot-0-0--1/smooth_fit/xx_000300_world_results.npz
        if args.world_results is not None:
            ap.error("Cannot use both --world_results and --world_results_dir.")
        base = Path(args.world_results_dir).expanduser().resolve()
        if not base.is_dir():
            raise FileNotFoundError(f"Not a directory: {base}")

        def _is_video_custom_world_results(p: Path) -> bool:
            if not p.is_file() or p.suffix != ".npz":
                return False
            if not p.name.endswith("_000300_world_results.npz"):
                return False
            if p.parent.name != "smooth_fit":
                return False
            if not p.parent.parent.name.endswith("-all-shot-0-0--1"):
                return False
            parts = p.parts
            if "logs" not in parts or "video-custom" not in parts:
                return False
            return True

        npz_files = sorted(
            p
            for p in base.rglob("*_000300_world_results.npz")
            if _is_video_custom_world_results(p)
        )
        if not npz_files:
            print(
                f"No matching world_results found under {base} "
                "(expect logs/video-custom/.../...-all-shot-0-0--1/smooth_fit/*_000300_world_results.npz)"
            )
            return
        print(f"Found {len(npz_files)} matching world_results NPZ file(s).")
        batch_summary: List[Dict] = []
        for world_results in npz_files:
            out_dir = world_results.parent.parent / args.out_subdir
            out_dir.mkdir(parents=True, exist_ok=True)
            print(f"\n{'=' * 60}\nProcessing: {world_results}")
            try:
                result = process_one(world_results, out_dir, args)
                if result is not None:
                    per_frame, threshold_info = result
                    num_frames = len(next(iter(per_frame.values())))
                    filtered_valid = per_frame.get("filtered_valid_mask")
                    if filtered_valid is not None and num_frames > 0:
                        invalid_count = sum(1 for x in filtered_valid if not x)
                        filtered_invalid_ratio = invalid_count / num_frames
                    else:
                        filtered_invalid_ratio = 0.0
                    try:
                        rel = world_results.relative_to(base)
                        video_id = (
                            rel.parts[0]
                            if rel.parts
                            else world_results.parent.parent.name
                        )
                    except ValueError:
                        video_id = world_results.parent.parent.name
                    batch_summary.append(
                        {
                            "world_results": str(world_results),
                            "video_id": video_id,
                            "num_frames": num_frames,
                            "frames_false_by_key": _summary_frames_false_by_key(
                                per_frame
                            ),
                            "trans_thr": threshold_info["trans_thr"],
                            "rot_thr_deg": threshold_info["rot_thr_deg"],
                            "filtered_invalid_ratio": filtered_invalid_ratio,
                        }
                    )
            except Exception as e:
                print(f"[ERROR] {world_results}: {e}")
                raise
        # Median thresholds and error_video flags
        trans_vals = [
            v["trans_thr"] for v in batch_summary if v.get("trans_thr") is not None
        ]
        rot_vals = [
            v["rot_thr_deg"] for v in batch_summary if v.get("rot_thr_deg") is not None
        ]
        median_trans = float(np.median(trans_vals)) if trans_vals else None
        median_rot_deg = float(np.median(rot_vals)) if rot_vals else None
        factor_trans = float(args.error_threshold_factor_trans)
        factor_rot = float(args.error_threshold_factor_rot)
        error_valid_ratio_thr = float(args.error_valid_ratio)
        error_video_ids: List[str] = []
        for v in batch_summary:
            is_error = False
            if median_trans is not None and v.get("trans_thr") is not None:
                if v["trans_thr"] > median_trans * factor_trans:
                    is_error = True
            if median_rot_deg is not None and v.get("rot_thr_deg") is not None:
                if v["rot_thr_deg"] > median_rot_deg * factor_rot:
                    is_error = True
            if v.get("filtered_invalid_ratio", 0.0) > error_valid_ratio_thr:
                is_error = True
            v["error_video"] = is_error
            if is_error:
                error_video_ids.append(v["video_id"])
        # Write batch summary
        if batch_summary:
            summary_path = base / "qc_world_jumpy_batch_summary.json"
            summary_data = {
                "world_results_dir": str(base),
                "num_videos": len(batch_summary),
                "median_trans_threshold": median_trans,
                "median_rot_threshold_deg": median_rot_deg,
                "error_threshold_factor_trans": factor_trans,
                "error_threshold_factor_rot": factor_rot,
                "error_valid_ratio": error_valid_ratio_thr,
                "error_video_ids": error_video_ids,
                "videos": batch_summary,
            }
            with open(summary_path, "w") as f:
                json.dump(summary_data, f, indent=2)
            print(f"\nSaved batch summary: {summary_path}")
            if error_video_ids:
                print(
                    f"Error videos (trans_thr > median*{factor_trans} or rot_thr_deg > median*{factor_rot} or filtered_invalid_ratio > {error_valid_ratio_thr}): {error_video_ids}"
                )
            else:
                print("No error videos (all within threshold and valid-ratio limits).")
        return

    # Single-file mode
    if args.world_results is None:
        ap.error("Either --world_results or --world_results_dir is required.")
    world_results = Path(args.world_results).expanduser().resolve()
    if not world_results.is_file():
        raise FileNotFoundError(world_results)
    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else world_results.parent
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    process_one(world_results, out_dir, args)


if __name__ == "__main__":
    main()
