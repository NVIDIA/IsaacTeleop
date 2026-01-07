#!/usr/bin/env python3
"""
Export OpenXR-26 joints (IsaacLab OpenXR ordering) from a Dyn-HaMR `*_world_results.npz`.
  - loads MANO params from the world-results file (supports pickled `world` dict)
  - runs MANO forward for all tracks/frames
  - converts MANO/OpenPose-21 joints to OpenXR-26 joint positions
  - writes `openxr26_joints.npz` with shape (B,T,26,3)

Example:
  python dyn-hamr/export_openxr26_from_world_results.py \\
    --world_results outputs/logs/.../smooth_fit/output_video_000300_world_results.npz \\
    --out_dir /tmp/openxr26

To export joints in a canonical MANO frame (no global rotation/translation), use:
  python dyn-hamr/export_openxr26_from_world_results.py \\
    --world_results ... \\
    --out_dir /tmp/openxr26 \\
    --zero_global

To also save handedness-split outputs:
  python dyn-hamr/export_openxr26_from_world_results.py \\
    --world_results ... \\
    --out_dir /tmp/openxr26 \\
    --split_by_handedness
"""

import os
import sys
import argparse


# Make imports work whether run from repo root or from inside dyn-hamr/
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)


from vis_mano_params import (  # noqa: E402
    load_mano_params_from_file,
    openpose21_to_openxr26_joints,
    HAND_JOINT_NAMES,
    _to_numpy,
)

import numpy as np  # noqa: E402
import torch  # noqa: E402
from omegaconf import OmegaConf  # noqa: E402

from body_model import MANO  # noqa: E402
from body_model.utils import run_mano  # noqa: E402
from util.loaders import resolve_cfg_paths  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--world_results", type=str, required=True, help="Path to `*_world_results.npz`")
    parser.add_argument("--out_dir", type=str, required=True)
    parser.add_argument("--cfg", type=str, default=os.path.join(THIS_DIR, "confs", "config.yaml"))
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--openxr_metacarpal_alpha", type=float, default=0.3)
    parser.add_argument(
        "--zero_global",
        action="store_true",
        help="If set, force MANO global translation/rotation to identity (trans=0, root_orient=0) before running MANO.",
    )
    parser.add_argument(
        "--zero_trans",
        action="store_true",
        help="If set, force MANO global translation to zero (trans=0) before running MANO.",
    )
    parser.add_argument(
        "--zero_root_orient",
        action="store_true",
        help="If set, force MANO global orientation to identity (root_orient=0 axis-angle) before running MANO.",
    )
    parser.add_argument(
        "--split_by_handedness",
        action="store_true",
        help=(
            "If set, also write `openxr26_joints_right.npz` and `openxr26_joints_left.npz` by splitting tracks (B) "
            "using `is_right` (assumes each track has consistent handedness across time)."
        ),
    )
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    device = torch.device(args.device)

    cfg = OmegaConf.load(args.cfg)
    cfg = resolve_cfg_paths(cfg)
    mano_cfg = {k.lower(): v for k, v in dict(cfg.MANO).items()}

    params = load_mano_params_from_file(args.world_results, device=device)
    B, T, _ = params.trans.shape

    if args.zero_global:
        params.trans = torch.zeros_like(params.trans)
        params.root_orient = torch.zeros_like(params.root_orient)
    else:
        if args.zero_trans:
            params.trans = torch.zeros_like(params.trans)
        if args.zero_root_orient:
            params.root_orient = torch.zeros_like(params.root_orient)

    hand_model = MANO(batch_size=B * T, pose2rot=True, **mano_cfg).to(device)

    is_right = params.is_right
    if is_right is None:
        is_right = torch.ones((B, T), device=device)

    out = run_mano(
        hand_model,
        trans=params.trans,
        root_orient=params.root_orient,
        body_pose=params.hand_pose,
        is_right=is_right,
        betas=params.betas,
    )

    joints_bt = _to_numpy(out["joints"])  # (B,T,21,3)
    if joints_bt.shape[2] != 21 or joints_bt.shape[-1] != 3:
        raise RuntimeError(f"Unexpected MANO joints shape: {joints_bt.shape} (expected (B,T,21,3))")

    j26 = np.zeros((B, T, 26, 3), dtype=np.float32)
    for b in range(B):
        for t in range(T):
            j26[b, t] = openpose21_to_openxr26_joints(
                joints_bt[b, t], metacarpal_alpha=float(args.openxr_metacarpal_alpha)
            )

    np.savez(
        os.path.join(args.out_dir, "openxr26_joints.npz"),
        joints_openxr26=j26,
        joint_names_openxr26=np.asarray(HAND_JOINT_NAMES, dtype=object),
        is_right=_to_numpy(is_right),
    )
    print(f"Wrote: {os.path.join(args.out_dir, 'openxr26_joints.npz')}")

    if args.split_by_handedness:
        is_right_np = _to_numpy(is_right)  # (B,T)
        if is_right_np.ndim != 2 or is_right_np.shape != (B, T):
            raise RuntimeError(f"Unexpected is_right shape: {is_right_np.shape} (expected (B,T))")

        # Track-level handedness decision (using frame 0), with a warning if it flips over time.
        track_right0 = is_right_np[:, 0] >= 0.5
        flips = (is_right_np >= 0.5) != track_right0[:, None]
        flip_tracks = np.where(np.any(flips, axis=1))[0]
        if flip_tracks.size > 0:
            print(
                f"[WARN] is_right changes over time for tracks: {flip_tracks.tolist()}. "
                "Splitting uses frame-0 handedness for the whole track."
            )

        right_idx = np.where(track_right0)[0].astype(np.int64)
        left_idx = np.where(~track_right0)[0].astype(np.int64)

        right_path = os.path.join(args.out_dir, "openxr26_joints_right.npz")
        left_path = os.path.join(args.out_dir, "openxr26_joints_left.npz")

        np.savez(
            right_path,
            joints_openxr26=j26[right_idx],
            joint_names_openxr26=np.asarray(HAND_JOINT_NAMES, dtype=object),
            is_right=is_right_np[right_idx],
            track_indices=right_idx,
        )
        np.savez(
            left_path,
            joints_openxr26=j26[left_idx],
            joint_names_openxr26=np.asarray(HAND_JOINT_NAMES, dtype=object),
            is_right=is_right_np[left_idx],
            track_indices=left_idx,
        )
        print(f"Wrote: {right_path} (B={len(right_idx)})")
        print(f"Wrote: {left_path} (B={len(left_idx)})")


if __name__ == "__main__":
    main()


