#!/usr/bin/env python3
"""
Post-process a retargeted TriHand trajectory NPZ to place/orient the wrist pose in Dyn-HaMR "world" coordinates,
WITHOUT re-running dex-retargeting.

Why this exists
---------------
`retarget_openxr26_with_g1_upper_body.py` can produce a trajectory NPZ containing:
  - left_hand_q / right_hand_q (joint angles)
  - left_wrist / right_wrist (optional wrist/base pose used by IsaacLab replay with --use_wrist_pose)

When you retarget from `--zero_global` OpenXR26 joints, the joint angles are correct but the wrist poses are
in a canonical frame near the origin. This script applies the per-frame MANO global transform
(root_orient + trans from the original `*_world_results.npz`) to the wrist pose trajectory so that Isaac replay
can teleport the hand to the world-view motion.

Notes on coordinate conventions
-------------------------------
Dyn-HaMR's `run_mano` applies an X-axis flip for left hands *after* applying the MANO global transform:
  J_world = F * (R * J0 + t), where F = diag(s,1,1), s=+1 (right) or -1 (left)

If your canonical pose is already in the "post-flip" frame (which is the case for the OpenXR26 exported by this repo),
then the equivalent rigid transform on canonical points is:
  J_world = (F R F) * J_canonical + (F t)

We use that same transform for wrist positions, and for orientation we convert (F R F) to a quaternion and
compose it with the existing wrist quaternion.

If the world axes still don't match Isaac world axes, use IsaacLab replay's `--wrist_pose_rot*` options
to apply an extra correction rotation at replay time.

Example
-------
python dyn-hamr/apply_world_pose_to_traj_npz.py \\
  --traj_npz_in  outputs/retarget/openxr26_single_hand_zero_global/left_hand_traj_optrot.npz \\
  --traj_npz_out outputs/retarget/openxr26_single_hand_zero_global/left_hand_traj_world.npz \\
  --world_results outputs/logs/.../smooth_fit/output_video_000000_world_results.npz \\
  --hand left \\
  --split_npz outputs/retarget/openxr26_single_hand_zero_global/openxr26_joints_left.npz \\
  --seq_track 0 \\
  --apply_to both

Then replay with:
  ./isaaclab.sh -p scripts/demos/unitree_trihand_replay_traj.py \\
    --traj_npz outputs/.../left_hand_traj_world.npz \\
    --hand left --spawn_height 0.3 --use_wrist_pose
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _aa_to_rotmat(aa: "np.ndarray") -> "np.ndarray":
    """Axis-angle (3,) to rotation matrix (3,3)."""
    import numpy as np

    aa = np.asarray(aa, dtype=np.float32).reshape(3)
    theta = float(np.linalg.norm(aa))
    if theta < 1e-8:
        return np.eye(3, dtype=np.float32)
    axis = aa / theta
    x, y, z = [float(v) for v in axis]
    K = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]], dtype=np.float32)
    I = np.eye(3, dtype=np.float32)
    s = float(np.sin(theta))
    c = float(np.cos(theta))
    return (I + s * K + (1.0 - c) * (K @ K)).astype(np.float32)


def _quat_mul_wxyz(q1: "np.ndarray", q2: "np.ndarray") -> "np.ndarray":
    import numpy as np

    q1 = np.asarray(q1, dtype=np.float32).reshape(4)
    q2 = np.asarray(q2, dtype=np.float32).reshape(4)
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        dtype=np.float32,
    )


def _quat_conj_wxyz(q: "np.ndarray") -> "np.ndarray":
    import numpy as np

    q = np.asarray(q, dtype=np.float32).reshape(4)
    return np.array([q[0], -q[1], -q[2], -q[3]], dtype=np.float32)


def _map_dynhamr_world_to_isaac(R_dh: "np.ndarray", t_dh: "np.ndarray") -> Tuple["np.ndarray", "np.ndarray"]:
    """
    Map a pose expressed in Dyn-HaMR world coordinates to Isaac world coordinates.

    Dyn-HaMR world convention (as documented in this repo): x right, y down, z forward
    Isaac world (USD typical): x forward, y left, z up

    We use axis mapping:
      x_isaac =  z_dh
      y_isaac = -x_dh
      z_isaac = -y_dh

    For rotations: R_isaac = M * R_dh * M^T
    For translations: t_isaac = M * t_dh
    """
    import numpy as np

    M = np.array(
        [
            [0.0, 0.0, 1.0],
            [-1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
        ],
        dtype=np.float32,
    )
    R_dh = np.asarray(R_dh, dtype=np.float32).reshape(3, 3)
    t_dh = np.asarray(t_dh, dtype=np.float32).reshape(3)
    R_i = (M @ R_dh @ M.T).astype(np.float32)
    t_i = (M @ t_dh).astype(np.float32)
    return R_i, t_i


def _quat_wxyz_from_rotmat(R: "np.ndarray") -> "np.ndarray":
    import numpy as np

    R = np.asarray(R, dtype=np.float32).reshape(3, 3)
    t = float(np.trace(R))
    if t > 0.0:
        s = float(np.sqrt(t + 1.0) * 2.0)
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    else:
        if R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
            s = float(np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0)
            w = (R[2, 1] - R[1, 2]) / s
            x = 0.25 * s
            y = (R[0, 1] + R[1, 0]) / s
            z = (R[0, 2] + R[2, 0]) / s
        elif R[1, 1] > R[2, 2]:
            s = float(np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0)
            w = (R[0, 2] - R[2, 0]) / s
            x = (R[0, 1] + R[1, 0]) / s
            y = 0.25 * s
            z = (R[1, 2] + R[2, 1]) / s
        else:
            s = float(np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0)
            w = (R[1, 0] - R[0, 1]) / s
            x = (R[0, 2] + R[2, 0]) / s
            y = (R[1, 2] + R[2, 1]) / s
            z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float32)
    q = q / max(float(np.linalg.norm(q)), 1e-8)
    return q


def _rot_x(a: float) -> "np.ndarray":
    import numpy as np

    ca, sa = float(np.cos(a)), float(np.sin(a))
    return np.array([[1.0, 0.0, 0.0], [0.0, ca, -sa], [0.0, sa, ca]], dtype=np.float32)


def _rot_y(a: float) -> "np.ndarray":
    import numpy as np

    ca, sa = float(np.cos(a)), float(np.sin(a))
    return np.array([[ca, 0.0, sa], [0.0, 1.0, 0.0], [-sa, 0.0, ca]], dtype=np.float32)


def _rot_z(a: float) -> "np.ndarray":
    import numpy as np

    ca, sa = float(np.cos(a)), float(np.sin(a))
    return np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)


def _euler_xyz_deg_to_rotmat(euler_xyz_deg: tuple[float, float, float]) -> "np.ndarray":
    """
    Intrinsic XYZ Euler (degrees) matching scipy's `Rotation.from_euler(\"xyz\", ...)`.
    """
    import numpy as np

    ax, ay, az = [float(v) * np.pi / 180.0 for v in euler_xyz_deg]
    return (_rot_x(ax) @ _rot_y(ay) @ _rot_z(az)).astype(np.float32)


def _parse_euler_xyz_deg(csv: str) -> tuple[float, float, float]:
    parts = [p.strip() for p in str(csv).split(",") if p.strip() != ""]
    if len(parts) != 3:
        raise ValueError(f"Expected 'x_deg,y_deg,z_deg' (3 numbers), got: {csv!r}")
    return float(parts[0]), float(parts[1]), float(parts[2])


def _parse_frame_indices_from_traj(traj: Dict[str, "np.ndarray"], *, T: int) -> "np.ndarray":
    import numpy as np

    if "frame_files" not in traj:
        return np.arange(T, dtype=np.int64)
    ff = traj["frame_files"]
    try:
        ff_list = [str(x) for x in ff.tolist()]
    except Exception:
        return np.arange(T, dtype=np.int64)

    idxs = []
    for s in ff_list:
        # expected format from our retargeter: "...::t=000123"
        if "::t=" in s:
            try:
                idxs.append(int(s.split("::t=")[-1]))
                continue
            except Exception:
                pass
        idxs.append(len(idxs))  # fallback monotonic
    return np.asarray(idxs, dtype=np.int64)


def _resolve_world_track(
    *,
    world_track: Optional[int],
    split_npz: Optional[Path],
    seq_track: int,
) -> int:
    if split_npz is None:
        if world_track is None:
            return int(seq_track)
        return int(world_track)

    import numpy as np

    with np.load(str(split_npz), allow_pickle=True) as d:
        if "track_indices" not in d.files:
            raise KeyError(f"{split_npz} missing key 'track_indices' (needed to map seq track -> world track).")
        ti = np.asarray(d["track_indices"]).reshape(-1)
        if seq_track < 0 or seq_track >= ti.shape[0]:
            raise ValueError(f"{split_npz}: --seq_track={seq_track} out of range for track_indices len={ti.shape[0]}")
        return int(ti[int(seq_track)])


def _load_world_params(world_results: Path) -> Tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """
    Returns (trans_bt3, root_orient_bt3, is_right_bt) as numpy arrays.
    """
    import numpy as np
    import torch

    # Make imports work when run from repo root or dyn-hamr/
    this_dir = Path(__file__).resolve().parent
    import sys

    if str(this_dir) not in sys.path:
        sys.path.insert(0, str(this_dir))

    from vis_mano_params import load_mano_params_from_file  # noqa: E402
    from vis_mano_params import _to_numpy  # noqa: E402

    params = load_mano_params_from_file(str(world_results), device=torch.device("cpu"))
    trans = _to_numpy(params.trans).astype(np.float32)  # (B,T,3)
    root = _to_numpy(params.root_orient).astype(np.float32)  # (B,T,3)
    is_right = params.is_right
    if is_right is None:
        is_right = torch.ones((trans.shape[0], trans.shape[1]), device=torch.device("cpu"))
    is_right = _to_numpy(is_right).astype(np.float32)  # (B,T)
    return trans, root, is_right


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traj_npz_in", type=str, required=True)
    ap.add_argument("--traj_npz_out", type=str, required=True)
    ap.add_argument("--world_results", type=str, required=True, help="Path to Dyn-HaMR `*_world_results.npz`.")
    ap.add_argument("--hand", type=str, choices=["left", "right"], required=True, help="Which wrist pose to update.")
    ap.add_argument(
        "--apply_to",
        type=str,
        choices=["pos", "quat", "both"],
        default="both",
        help="Apply world transform to position, quaternion, or both (default: both).",
    )
    ap.add_argument(
        "--quat_order",
        type=str,
        choices=["pre", "post"],
        default="pre",
        help="Quaternion composition order when applying world rotation: pre => q_out=qR⊗q, post => q_out=q⊗qR.",
    )
    ap.add_argument(
        "--world_track",
        type=int,
        default=None,
        help="Track index (B) in the *world_results* file. If --split_npz is given, this is ignored.",
    )
    ap.add_argument(
        "--split_npz",
        type=str,
        default=None,
        help=(
            "Optional path to `openxr26_joints_left.npz` / `openxr26_joints_right.npz` generated with "
            "`--split_by_handedness`. Used to map `--seq_track` to the original world_results track via `track_indices`."
        ),
    )
    ap.add_argument(
        "--seq_track",
        type=int,
        default=0,
        help="Track index within the split_npz (or default world_track if split_npz is not provided).",
    )
    ap.add_argument(
        "--to_isaac_world",
        action="store_true",
        help=(
            "If set, additionally convert the resulting wrist pose from Dyn-HaMR world (x right, y down, z forward) "
            "to Isaac world (x forward, y left, z up). Applies to BOTH position and quaternion."
        ),
    )
    ap.add_argument(
        "--pre_rot",
        type=str,
        default=None,
        help=(
            "Optional extra fixed rotation (XYZ Euler degrees, 'x_deg,y_deg,z_deg') applied to the wrist quaternion "
            "BEFORE composing the Dyn-HaMR world rotation. This is the correct place to compensate for the "
            "`retarget_openxr26_with_g1_upper_body.py --apply-rot` that was used to rotate joint POSITIONS for retargeting "
            "(since that rotation is otherwise missing from the wrist ORIENTATION). "
            "Recommended when your finger motion is correct but the teleported wrist orientation looks wrong."
        ),
    )
    args = ap.parse_args()

    import numpy as np

    traj_in = Path(args.traj_npz_in).expanduser().resolve()
    traj_out = Path(args.traj_npz_out).expanduser().resolve()
    world_results = Path(args.world_results).expanduser().resolve()
    split_npz = None if args.split_npz is None else Path(args.split_npz).expanduser().resolve()

    if not traj_in.is_file():
        raise FileNotFoundError(traj_in)
    if not world_results.is_file():
        raise FileNotFoundError(world_results)
    if split_npz is not None and not split_npz.is_file():
        raise FileNotFoundError(split_npz)

    # Load trajectory
    with np.load(str(traj_in), allow_pickle=True) as d:
        traj: Dict[str, np.ndarray] = {k: d[k] for k in d.files}

    wrist_key = "left_wrist" if args.hand == "left" else "right_wrist"
    if wrist_key not in traj:
        raise KeyError(f"{traj_in} missing '{wrist_key}'. Found keys: {list(traj.keys())}")
    wrist = np.asarray(traj[wrist_key], dtype=np.float32)
    if wrist.ndim != 2 or wrist.shape[1] != 7:
        raise ValueError(f"{wrist_key} must be (T,7). Got {wrist.shape}")
    T = int(wrist.shape[0])
    t_idxs = _parse_frame_indices_from_traj(traj, T=T)

    # Load world params and select track
    trans_btc, root_btc, is_right_bt = _load_world_params(world_results)
    B, Tw, _ = trans_btc.shape
    world_track = _resolve_world_track(world_track=args.world_track, split_npz=split_npz, seq_track=int(args.seq_track))
    if world_track < 0 or world_track >= B:
        raise ValueError(f"world_track={world_track} out of range for world_results B={B}")

    # Build output wrist array
    out = wrist.copy()
    do_pos = args.apply_to in ("pos", "both")
    do_quat = args.apply_to in ("quat", "both")
    q_pre = None
    if args.pre_rot is not None:
        R_pre = _euler_xyz_deg_to_rotmat(_parse_euler_xyz_deg(args.pre_rot))
        q_pre = _quat_wxyz_from_rotmat(R_pre)

    for i in range(T):
        t = int(t_idxs[i])
        if t < 0 or t >= Tw:
            continue
        trans = np.asarray(trans_btc[world_track, t], dtype=np.float32).reshape(3)
        aa = np.asarray(root_btc[world_track, t], dtype=np.float32).reshape(3)
        s = 1.0 if float(is_right_bt[world_track, t]) >= 0.5 else -1.0
        F = np.diag(np.array([s, 1.0, 1.0], dtype=np.float32))

        R = _aa_to_rotmat(aa)
        Rw = (F @ R @ F).astype(np.float32)
        tw = (F @ trans).astype(np.float32)

        if args.to_isaac_world:
            Rw, tw = _map_dynhamr_world_to_isaac(Rw, tw)

        if do_pos:
            p = out[i, :3].astype(np.float32)
            out[i, :3] = (Rw @ p + tw).astype(np.float32)
        if do_quat:
            q = out[i, 3:].astype(np.float32)
            # Apply pre-rotation in the wrist/local chain BEFORE composing world rotation.
            # This results in: q_out = qR ⊗ (q_pre ⊗ q) when quat_order=pre.
            if q_pre is not None:
                q = _quat_mul_wxyz(q_pre, q)
            qR = _quat_wxyz_from_rotmat(Rw)
            if args.quat_order == "post":
                q_out = _quat_mul_wxyz(q, qR)
            else:
                q_out = _quat_mul_wxyz(qR, q)
            q_out = q_out / max(float(np.linalg.norm(q_out)), 1e-8)
            out[i, 3:] = q_out.astype(np.float32)

    traj[wrist_key] = out

    # Provenance (replay ignores unknown keys)
    traj["world_results_file"] = np.array(str(world_results), dtype=object)
    traj["world_track"] = np.array(int(world_track), dtype=np.int64)
    traj["seq_track"] = np.array(int(args.seq_track), dtype=np.int64)
    traj["applied_to"] = np.array(str(args.apply_to), dtype=object)
    traj["quat_order"] = np.array(str(args.quat_order), dtype=object)
    traj["hand_updated"] = np.array(str(args.hand), dtype=object)

    traj_out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(str(traj_out), **traj)
    print(f"Wrote: {traj_out}")


if __name__ == "__main__":
    main()


