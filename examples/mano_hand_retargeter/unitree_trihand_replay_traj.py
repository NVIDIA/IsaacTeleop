#!/usr/bin/env python3
"""
Replay a saved TriHand joint trajectory (from Dyn-HaMR OpenXR26 retargeting) in Isaac Sim.

Expected trajectory NPZ format (written by `vis_mano_lw_openxr26/retarget_openxr26_with_g1_upper_body.py`):
  - right_hand_q: (T, 7) float32
  - right_dof_names: (7,) object (joint names)
  - frame_dt: float (seconds between frames)
Optionally (for world-view placement):
  - left_wrist: (T, 7) float32  [x,y,z,qw,qx,qy,qz] in USD control frame
  - right_wrist: (T, 7) float32 [x,y,z,qw,qx,qy,qz] in USD control frame

Usage:
  ./isaaclab.sh -p scripts/demos/unitree_trihand_replay_traj.py \
    --traj_npz /abs/path/to/right_hand_traj.npz \
    --hand right \
    --spawn_height 0.3
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

try:
    # Preferred: IsaacLab available on PYTHONPATH (e.g., when launched via `isaaclab.sh -p ...`)
    from isaaclab.app import AppLauncher
except ModuleNotFoundError as e:
    # Fallback: allow running directly if ISAACLAB_PATH points to an IsaacLab checkout.
    import sys

    isaaclab_path = os.environ.get("ISAACLAB_PATH")
    if isaaclab_path:
        # Your layout is:
        #   $ISAACLAB_PATH/source/isaaclab/isaaclab/app/...
        # so we must add `$ISAACLAB_PATH/source/isaaclab` (the parent of the `isaaclab/` package)
        # to sys.path.
        candidate_roots = [
            os.path.join(isaaclab_path, "source", "isaaclab"),
            os.path.join(isaaclab_path, "source"),
        ]
        for root in candidate_roots:
            if os.path.isdir(os.path.join(root, "isaaclab")) and root not in sys.path:
                sys.path.insert(0, root)
        try:
            from isaaclab.app import AppLauncher  # type: ignore
        except ModuleNotFoundError:
            raise ModuleNotFoundError(
                "Could not import `isaaclab`. Run this script via IsaacLab:\n"
                "  $ISAACLAB_PATH/isaaclab.sh -p /abs/path/to/unitree_trihand_replay_traj.py\n"
                "or ensure `$ISAACLAB_PATH/source/isaaclab` is on PYTHONPATH."
            ) from e
    else:
        raise ModuleNotFoundError(
            "Could not import `isaaclab` and ISAACLAB_PATH is not set.\n"
            "Set it to your IsaacLab repo root (with `source/isaaclab`), or run via `isaaclab.sh`."
        ) from e


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Unitree TriHand trajectory in Isaac Sim.")
    parser.add_argument(
        "--traj_npz",
        type=str,
        default=None,
        help=(
            "Trajectory npz for single-hand replay (contains *_hand_q and *_dof_names). "
            "For --hand both, use --traj_npz_left and --traj_npz_right instead."
        ),
    )
    parser.add_argument("--traj_npz_left", type=str, default=None, help="Left-hand trajectory npz (required for --hand both).")
    parser.add_argument("--traj_npz_right", type=str, default=None, help="Right-hand trajectory npz (required for --hand both).")
    parser.add_argument("--hand", choices=["right", "left", "both"], default="right", help="Which hand(s) to replay.")
    parser.add_argument("--spawn_height", type=float, default=0.3, help="Spawn height above ground (meters).")
    parser.add_argument(
        "--ground_z",
        type=float,
        default=0.0,
        help="Ground plane Z position in world meters (default: 0.0). Use a large negative value to move it far below.",
    )
    parser.add_argument("--no_ground", action="store_true", help="If set, do not spawn a ground plane.")
    parser.add_argument(
        "--hand_spacing",
        type=float,
        default=0.18,
        help="When --hand both, X-axis spacing between the two hands (meters).",
    )
    parser.add_argument(
        "--use_wrist_pose",
        action="store_true",
        help=(
            "If set and the trajectory NPZ contains left_wrist/right_wrist, "
            "teleport the hand base each frame to that pose (world-view replay)."
        ),
    )
    parser.add_argument(
        "--wrist_z_offset",
        type=float,
        default=0.0,
        help="Optional z offset (meters) added to wrist pose when --use_wrist_pose is enabled.",
    )
    parser.add_argument(
        "--wrist_pose_rot",
        type=str,
        default=None,
        help=(
            "Optional extra rotation applied to wrist WORLD poses before teleporting, as 'x_deg,y_deg,z_deg' "
            "(XYZ Euler degrees). Useful to fix a coordinate-frame mismatch."
        ),
    )
    parser.add_argument(
        "--wrist_pose_rot_left",
        type=str,
        default=None,
        help="Optional extra rotation for LEFT wrist pose only (overrides --wrist_pose_rot for left).",
    )
    parser.add_argument(
        "--wrist_pose_rot_right",
        type=str,
        default=None,
        help="Optional extra rotation for RIGHT wrist pose only (overrides --wrist_pose_rot for right).",
    )
    parser.add_argument(
        "--wrist_pose_rot_pivot",
        type=str,
        default="0,0,0",
        help=(
            "Pivot for --wrist_pose_rot{,_left,_right} rotation, as 'x,y,z' in world meters (default: 0,0,0). "
            "Position is rotated about this pivot."
        ),
    )
    parser.add_argument(
        "--wrist_pose_rot_only_orientation",
        action="store_true",
        help="If set, apply wrist pose rotation ONLY to the quaternion (do not rotate the position trajectory).",
    )
    parser.add_argument(
        "--wrist_pose_rot_order",
        type=str,
        default="pre",
        choices=["pre", "post"],
        help=(
            "How to compose the extra wrist rotation with the incoming quaternion. "
            "'pre' = q_out = qR ⊗ q (rotate in world). "
            "'post' = q_out = q ⊗ qR (rotate in local/body)."
        ),
    )
    parser.add_argument(
        "--wrist_to_root_offset_left",
        type=str,
        default="0,0,0",
        help=(
            "Translate the spawned LEFT URDF root relative to the incoming wrist pose by this local offset "
            "(meters) expressed in the wrist frame, as 'x,y,z'. This compensates for URDF root not being at wrist."
        ),
    )
    parser.add_argument(
        "--wrist_to_root_offset_right",
        type=str,
        default="0,0,0",
        help=(
            "Translate the spawned RIGHT URDF root relative to the incoming wrist pose by this local offset "
            "(meters) expressed in the wrist frame, as 'x,y,z'."
        ),
    )
    parser.add_argument(
        "--print_body_names",
        action="store_true",
        help="If set, print available rigid-body (link) names for each spawned hand and exit.",
    )
    parser.add_argument(
        "--suggest_wrist_to_root_offset",
        action="store_true",
        help=(
            "If set, compute and print a suggested --wrist_to_root_offset_{left,right} that makes a chosen link "
            "coincide with the incoming wrist POSITION at the held frame (use with --stop_frame). "
            "This avoids relying on UI transforms, which may not reflect physics state."
        ),
    )
    parser.add_argument(
        "--suggest_link_left",
        type=str,
        default="left_hand_palm_link",
        help="Link name to align to the incoming LEFT wrist position when --suggest_wrist_to_root_offset is set.",
    )
    parser.add_argument(
        "--suggest_link_right",
        type=str,
        default="right_hand_palm_link",
        help="Link name to align to the incoming RIGHT wrist position when --suggest_wrist_to_root_offset is set.",
    )
    parser.add_argument(
        "--print_wrist_stats",
        action="store_true",
        help="If set, print basic stats for left/right wrist trajectories and their relative displacement.",
    )
    parser.add_argument("--stiffness", type=float, default=50.0, help="Joint drive stiffness (PD).")
    parser.add_argument("--damping", type=float, default=5.0, help="Joint drive damping (PD).")
    parser.add_argument(
        "--mesh_dir",
        type=str,
        default=None,
        help=(
            "Optional local directory containing the URDF's `meshes/*.STL` files. "
            "If provided, the script will stage a copy of the URDF with a `meshes/` symlink next to it."
        ),
    )
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier (1.0 = realtime frame_dt).")
    parser.add_argument(
        "--camera_yaw_deg",
        type=float,
        default=0.0,
        help=(
            "Rotate the default camera eye position about world +Z around the camera target by this yaw (degrees). "
            "Positive values rotate the view to the left (counter-clockwise when looking down +Z)."
        ),
    )
    parser.add_argument(
        "--camera_pitch_deg",
        type=float,
        default=0.0,
        help=(
            "Rotate the default camera eye position about world +Y around the camera target by this pitch (degrees). "
            "Positive values pitch the view down toward the ground (right-hand rule about +Y)."
        ),
    )
    parser.add_argument(
        "--camera_roll_deg",
        type=float,
        default=0.0,
        help=(
            "Rotate the default camera eye position about world +X around the camera target by this roll (degrees). "
            "This is the third orbit rotation (after yaw/pitch). Positive values follow the right-hand rule about +X."
        ),
    )
    parser.add_argument(
        "--camera_target",
        type=str,
        default=None,
        help="Optional camera target override as 'x,y,z' in world meters (overrides --camera_target_mode).",
    )
    parser.add_argument(
        "--camera_target_mode",
        type=str,
        choices=["fixed", "wrist_mean"],
        default="fixed",
        help=(
            "How to choose the camera target. "
            "'fixed' uses (0,0,spawn_height) (default). "
            "'wrist_mean' uses the mean of available wrist positions at --start_frame (requires wrist poses)."
        ),
    )
    parser.add_argument(
        "--print_camera",
        action="store_true",
        help="If set, print the final camera eye/target used for sim.set_camera_view().",
    )
    parser.add_argument(
        "--camera_preset",
        type=str,
        choices=["default", "dynhamr_front"],
        default="default",
        help=(
            "Camera preset to roughly match Dyn-HaMR `run_vis.py` viewpoints. "
            "'default' uses the script's default eye offset. "
            "'dynhamr_front' matches Dyn-HaMR's static 'front' view direction (camera below + in front of target)."
        ),
    )
    parser.add_argument(
        "--camera_dir",
        type=str,
        default=None,
        help=(
            "Optional camera viewing direction override as 'x,y,z' in world space. The camera eye will be placed at "
            "`target + dist * normalize(camera_dir)` so that it looks toward the target from that direction. "
            "Example: --camera_target 0,0,0 --camera_dir -1,1,1."
        ),
    )
    parser.add_argument(
        "--camera_dist",
        type=float,
        default=None,
        help=(
            "Optional camera distance used with --camera_dir (meters). If not set, uses the default orbit radius."
        ),
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="If set, loop playback indefinitely (until the Isaac Sim window is closed).",
    )
    parser.add_argument("--start_frame", type=int, default=0, help="Start playback from this frame index (default: 0).")
    parser.add_argument(
        "--stop_frame",
        type=int,
        default=None,
        help=(
            "If set, stop advancing once this frame index is reached and HOLD that pose indefinitely "
            "(until the Isaac Sim window is closed)."
        ),
    )
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()

    # launch isaac sim
    app_launcher = AppLauncher(args)
    simulation_app = app_launcher.app

    import numpy as np
    import torch
    import isaaclab.sim as sim_utils
    import isaaclab.sim.utils.prims as prim_utils
    from isaaclab.actuators import ImplicitActuatorCfg
    from isaaclab.assets import Articulation, ArticulationCfg
    from isaaclab.utils.assets import ISAACLAB_NUCLEUS_DIR, retrieve_file_path

    def _load_traj(traj_npz_path: str, *, hand: str) -> tuple[np.ndarray, list[str], float, Path, dict[str, np.ndarray]]:
        traj_path = Path(traj_npz_path).expanduser().resolve()
        if not traj_path.is_file():
            raise FileNotFoundError(traj_path)
        traj = np.load(str(traj_path), allow_pickle=True)

        if hand == "right":
            q_key = "right_hand_q"
            n_key = "right_dof_names"
        else:
            q_key = "left_hand_q"
            n_key = "left_dof_names"

        if q_key not in traj.files or n_key not in traj.files:
            raise KeyError(f"Trajectory npz missing '{q_key}' or '{n_key}'. Found keys: {traj.files}")

        q_seq = np.asarray(traj[q_key], dtype=np.float32)
        dof_names = [str(x) for x in traj[n_key].tolist()]
        frame_dt = float(np.asarray(traj.get("frame_dt", 1.0 / 30.0)).reshape(()))
        if q_seq.ndim != 2:
            raise ValueError(f"{q_key} must be (T, dof). Got {q_seq.shape}")
        print(f"[traj] loaded ({hand}): {traj_path}")
        print(f"[traj] key={q_key} shape={q_seq.shape} dt={frame_dt:.4f}s")
        if q_seq.size > 0:
            q_min = float(np.min(q_seq))
            q_max = float(np.max(q_seq))
            q_std = np.std(q_seq, axis=0)
            print(f"[traj] q min/max: {q_min:+.4f} / {q_max:+.4f}")
            print(f"[traj] per-joint std: {q_std}")
            if float(np.max(q_std)) < 1e-4:
                print(f"[traj][WARN] {hand} trajectory is nearly constant (std ~0). The hand may look not moving.")
        extras = {}
        # optional wrist poses (USD control frame)
        if "left_wrist" in traj.files:
            extras["left_wrist"] = np.asarray(traj["left_wrist"], dtype=np.float32)
        if "right_wrist" in traj.files:
            extras["right_wrist"] = np.asarray(traj["right_wrist"], dtype=np.float32)
        return q_seq, dof_names, frame_dt, traj_path, extras

    def _parse_floats(name: str, s: str, n: int) -> list[float]:
        parts = [p.strip() for p in str(s).split(",") if p.strip() != ""]
        if len(parts) != n:
            raise ValueError(f"{name} must have {n} comma-separated numbers. Got: {s!r}")
        try:
            return [float(x) for x in parts]
        except Exception as e:
            raise ValueError(f"{name} could not parse floats from {s!r}") from e

    def _rot_x(a):
        ca, sa = float(np.cos(a)), float(np.sin(a))
        return np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]], dtype=np.float32)

    def _rot_y(a):
        ca, sa = float(np.cos(a)), float(np.sin(a))
        return np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]], dtype=np.float32)

    def _rot_z(a):
        ca, sa = float(np.cos(a)), float(np.sin(a))
        return np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]], dtype=np.float32)

    def _euler_xyz_deg_to_rotmat(euler_xyz_deg: tuple[float, float, float]) -> np.ndarray:
        # Intrinsic XYZ (matches scipy's from_euler("xyz", ...)) by right-multiplication.
        ax, ay, az = [float(v) * np.pi / 180.0 for v in euler_xyz_deg]
        return (_rot_x(ax) @ _rot_y(ay) @ _rot_z(az)).astype(np.float32)

    def _quat_mul_wxyz(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
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

    def _quat_wxyz_from_rotmat(R: np.ndarray) -> np.ndarray:
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

    def _quat_apply_wxyz(q: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Rotate vector v by quaternion q (wxyz)."""
        q = np.asarray(q, dtype=np.float32).reshape(4)
        v = np.asarray(v, dtype=np.float32).reshape(3)
        w, x, y, z = q
        qv = np.array([0.0, v[0], v[1], v[2]], dtype=np.float32)
        q_conj = np.array([w, -x, -y, -z], dtype=np.float32)
        return _quat_mul_wxyz(_quat_mul_wxyz(q, qv), q_conj)[1:]

    def _quat_conj_wxyz(q: np.ndarray) -> np.ndarray:
        q = np.asarray(q, dtype=np.float32).reshape(4)
        return np.array([q[0], -q[1], -q[2], -q[3]], dtype=np.float32)

    def _quat_inv_wxyz(q: np.ndarray) -> np.ndarray:
        q = np.asarray(q, dtype=np.float32).reshape(4)
        n2 = float(np.dot(q, q))
        if n2 < 1e-12:
            return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        return _quat_conj_wxyz(q) / n2

    pivot_xyz = np.asarray(_parse_floats("--wrist_pose_rot_pivot", args.wrist_pose_rot_pivot, 3), dtype=np.float32)

    rot_global = None
    if args.wrist_pose_rot is not None:
        rot_global = tuple(_parse_floats("--wrist_pose_rot", args.wrist_pose_rot, 3))
    rot_left = None
    if args.wrist_pose_rot_left is not None:
        rot_left = tuple(_parse_floats("--wrist_pose_rot_left", args.wrist_pose_rot_left, 3))
    rot_right = None
    if args.wrist_pose_rot_right is not None:
        rot_right = tuple(_parse_floats("--wrist_pose_rot_right", args.wrist_pose_rot_right, 3))

    R_left = _euler_xyz_deg_to_rotmat(rot_left if rot_left is not None else rot_global) if (rot_left or rot_global) else None
    R_right = _euler_xyz_deg_to_rotmat(rot_right if rot_right is not None else rot_global) if (rot_right or rot_global) else None
    qR_left = _quat_wxyz_from_rotmat(R_left) if R_left is not None else None
    qR_right = _quat_wxyz_from_rotmat(R_right) if R_right is not None else None

    def _apply_wrist_pose_rot(pose_wxyz: np.ndarray, *, hand: str) -> np.ndarray:
        pose = np.asarray(pose_wxyz, dtype=np.float32).reshape(7).copy()
        if hand == "left":
            R = R_left
            qR = qR_left
        else:
            R = R_right
            qR = qR_right
        if R is None or qR is None:
            return pose
        pos = pose[:3]
        quat = pose[3:]
        if args.wrist_pose_rot_only_orientation:
            pos_out = pos
        else:
            pos_out = (R @ (pos - pivot_xyz)) + pivot_xyz

        # Compose rotation with the quaternion.
        # - pre: rotate in world frame
        # - post: rotate in local/body frame
        if args.wrist_pose_rot_order == "post":
            quat_out = _quat_mul_wxyz(quat, qR)
        else:
            quat_out = _quat_mul_wxyz(qR, quat)
        pose[:3] = pos_out
        pose[3:] = quat_out / max(float(np.linalg.norm(quat_out)), 1e-8)
        return pose

    # Wrist->URDF-root local offsets (in wrist frame).
    wrist_to_root_left = np.asarray(_parse_floats("--wrist_to_root_offset_left", args.wrist_to_root_offset_left, 3), dtype=np.float32)
    wrist_to_root_right = np.asarray(_parse_floats("--wrist_to_root_offset_right", args.wrist_to_root_offset_right, 3), dtype=np.float32)

    def _apply_wrist_to_root_offset(pose_wxyz: np.ndarray, *, hand: str) -> np.ndarray:
        pose = np.asarray(pose_wxyz, dtype=np.float32).reshape(7).copy()
        off = wrist_to_root_left if hand == "left" else wrist_to_root_right
        if float(np.linalg.norm(off)) < 1e-12:
            return pose
        pos = pose[:3]
        quat = pose[3:]
        pos = pos + _quat_apply_wxyz(quat, off)
        pose[:3] = pos
        return pose

    # Determine which trajectories to load.
    if args.hand in ("left", "right"):
        if args.traj_npz is None:
            raise ValueError("--traj_npz is required for single-hand replay.")
        if args.hand == "right":
            q_right, names_right, frame_dt_right, traj_right_path, extras_right = _load_traj(args.traj_npz, hand="right")
            q_left = None
            names_left = None
            frame_dt_left = None
            traj_left_path = None
            extras_left = {}
        else:
            q_left, names_left, frame_dt_left, traj_left_path, extras_left = _load_traj(args.traj_npz, hand="left")
            q_right = None
            names_right = None
            frame_dt_right = None
            traj_right_path = None
            extras_right = {}
    else:
        # For backward compatibility, allow either:
        #  - a single --traj_npz that contains both left/right arrays, OR
        #  - separate --traj_npz_left/--traj_npz_right.
        if args.traj_npz is not None:
            q_left, names_left, frame_dt_left, traj_left_path, extras_left = _load_traj(args.traj_npz, hand="left")
            q_right, names_right, frame_dt_right, traj_right_path, extras_right = _load_traj(args.traj_npz, hand="right")
        else:
            if args.traj_npz_left is None or args.traj_npz_right is None:
                raise ValueError("--traj_npz_left and --traj_npz_right are required for --hand both (or pass --traj_npz).")
            q_left, names_left, frame_dt_left, traj_left_path, extras_left = _load_traj(args.traj_npz_left, hand="left")
            q_right, names_right, frame_dt_right, traj_right_path, extras_right = _load_traj(args.traj_npz_right, hand="right")
        # Keep the playback synchronized: require matching frame dt.
        if abs(float(frame_dt_left) - float(frame_dt_right)) > 1e-6:
            raise ValueError(
                f"Left and right trajectories have different frame_dt: left={frame_dt_left} right={frame_dt_right}. "
                "Regenerate with the same --traj-frame-dt."
            )

    if args.print_wrist_stats:
        def _stats(name: str, arr: np.ndarray):
            arr = np.asarray(arr, dtype=np.float32)
            if arr.size == 0:
                print(f"[wrist][{name}] empty")
                return
            p = arr[:, :3]
            print(f"[wrist][{name}] pos min={p.min(axis=0)} max={p.max(axis=0)} mean={p.mean(axis=0)} std={p.std(axis=0)}")
        wl = extras_left.get("left_wrist", None)
        wr = extras_right.get("right_wrist", None)
        if wl is not None:
            _stats("left", wl)
        if wr is not None:
            _stats("right", wr)
        if wl is not None and wr is not None:
            T0 = min(int(wl.shape[0]), int(wr.shape[0]))
            d = wl[:T0, :3] - wr[:T0, :3]
            print(f"[wrist][left-right] min={d.min(axis=0)} max={d.max(axis=0)} mean={d.mean(axis=0)} std={d.std(axis=0)}")

    # simulation
    sim_cfg = sim_utils.SimulationCfg(dt=0.01, device=args.device)
    sim = sim_utils.SimulationContext(sim_cfg)
    # Camera target selection.
    # By default, target is fixed at (0,0,spawn_height). For a viewport-like orbit around the hands, use wrist_mean.
    if args.camera_target is not None:
        target = np.asarray(_parse_floats("--camera_target", args.camera_target, 3), dtype=np.float32)
    elif args.camera_target_mode == "wrist_mean":
        # Try to use wrist mean at the start frame (only works if wrist poses exist).
        t0 = int(max(args.start_frame, 0))
        pts = []
        if args.hand in ("left", "both"):
            wl = extras_left.get("left_wrist", None)
            if wl is not None and wl.shape[0] > t0:
                pts.append(np.asarray(wl[t0], dtype=np.float32)[:3])
        if args.hand in ("right", "both"):
            wr = extras_right.get("right_wrist", None)
            if wr is not None and wr.shape[0] > t0:
                pts.append(np.asarray(wr[t0], dtype=np.float32)[:3])
        if pts:
            target = np.mean(np.stack(pts, axis=0), axis=0).astype(np.float32)
        else:
            target = np.array([0.0, 0.0, float(args.spawn_height)], dtype=np.float32)
    else:
        target = np.array([0.0, 0.0, float(args.spawn_height)], dtype=np.float32)

    # Camera: yaw (about world +Z), pitch (about world +Y), roll (about world +X) orbit of the eye around target.
    eye0 = np.array([0.35, -0.35, 0.40], dtype=np.float32)
    radius = float(np.linalg.norm(eye0 - target))

    # Base orbit vector v (from target to eye) before yaw/pitch/roll.
    if args.camera_dir is not None:
        dir_v = np.asarray(_parse_floats("--camera_dir", args.camera_dir, 3), dtype=np.float32)
        n = float(np.linalg.norm(dir_v))
        if n < 1e-8:
            raise ValueError("--camera_dir must have non-zero norm")
        dir_v = dir_v / n
        dist = radius if args.camera_dist is None else float(args.camera_dist)
        v = (dist * dir_v).astype(np.float32)
    elif args.camera_preset == "dynhamr_front":
        # Dyn-HaMR front view (in its 'right up back' coords) uses offset [0, -0.5, -1].
        # Mapping to Isaac world (x forward, y left, z up) gives direction approx [ +1, 0, -0.5 ].
        dir_v = np.array([1.0, 0.0, -0.5], dtype=np.float32)
        dir_v = dir_v / max(float(np.linalg.norm(dir_v)), 1e-8)
        v = (radius * dir_v).astype(np.float32)
    else:
        v = (eye0 - target).astype(np.float32)
    yaw = float(args.camera_yaw_deg) * np.pi / 180.0
    pitch = float(args.camera_pitch_deg) * np.pi / 180.0
    roll = float(args.camera_roll_deg) * np.pi / 180.0
    if abs(yaw) > 1e-12:
        c, s = float(np.cos(yaw)), float(np.sin(yaw))
        Rz = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
        v = (Rz @ v).astype(np.float32)
    if abs(pitch) > 1e-12:
        c, s = float(np.cos(pitch)), float(np.sin(pitch))
        Ry = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=np.float32)
        v = (Ry @ v).astype(np.float32)
    if abs(roll) > 1e-12:
        c, s = float(np.cos(roll)), float(np.sin(roll))
        Rx = np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=np.float32)
        v = (Rx @ v).astype(np.float32)
    eye = v + target
    if args.print_camera:
        print(
            f"[camera] eye={eye.tolist()} target={target.tolist()} "
            f"yaw={args.camera_yaw_deg} pitch={args.camera_pitch_deg} roll={args.camera_roll_deg}"
        )
    sim.set_camera_view(eye=eye.tolist(), target=target.tolist())
    if not args.no_ground:
        sim_utils.GroundPlaneCfg().func(
            "/World/GroundPlane",
            sim_utils.GroundPlaneCfg(),
            translation=(0.0, 0.0, float(args.ground_z)),
        )
    sim_utils.DomeLightCfg(intensity=2500.0, color=(0.8, 0.8, 0.8)).func("/World/Light", sim_utils.DomeLightCfg())

    prim_utils.create_prim("/World/Robot", "Xform")
    def _make_hand(prim_path: str, *, hand: str, pos_xyz: tuple[float, float, float]) -> Articulation:
        if hand == "right":
            urdf_nucleus = (
                f"{ISAACLAB_NUCLEUS_DIR}/Controllers/LocomanipulationAssets/unitree_g1_dexpilot_asset/G1_right_hand.urdf"
            )
        else:
            urdf_nucleus = (
                f"{ISAACLAB_NUCLEUS_DIR}/Controllers/LocomanipulationAssets/unitree_g1_dexpilot_asset/G1_left_hand.urdf"
            )
        hand_urdf_local = retrieve_file_path(urdf_nucleus, force_download=False)
        print(f"[urdf] {hand}: {hand_urdf_local}")

        # Optional mesh staging for visibility.
        if args.mesh_dir is not None:
            mesh_dir = Path(args.mesh_dir).expanduser().resolve()
            if not mesh_dir.is_dir():
                raise FileNotFoundError(f"--mesh_dir does not exist or is not a directory: {mesh_dir}")

            src_urdf = Path(hand_urdf_local).resolve()
            stage_dir = Path(tempfile.mkdtemp(prefix=f"isaaclab_trihand_replay_{hand}_"))
            staged_urdf = stage_dir / src_urdf.name
            shutil.copyfile(src_urdf, staged_urdf)

            meshes_link = stage_dir / "meshes"
            try:
                if meshes_link.exists() or meshes_link.is_symlink():
                    if meshes_link.is_dir() and not meshes_link.is_symlink():
                        shutil.rmtree(meshes_link)
                    else:
                        meshes_link.unlink()
                os.symlink(str(mesh_dir), str(meshes_link))
            except OSError as e:
                raise RuntimeError(f"Failed to create meshes symlink '{meshes_link}' -> '{mesh_dir}': {e}") from e
            hand_urdf_local = str(staged_urdf)

        cfg = ArticulationCfg(
            prim_path=prim_path,
            spawn=sim_utils.UrdfFileCfg(
                asset_path=str(hand_urdf_local),
                fix_base=True,
                joint_drive=sim_utils.UrdfConverterCfg.JointDriveCfg(
                    gains=sim_utils.UrdfConverterCfg.JointDriveCfg.PDGainsCfg(
                        stiffness=float(args.stiffness), damping=float(args.damping)
                    ),
                    target_type="position",
                ),
            ),
            init_state=ArticulationCfg.InitialStateCfg(pos=pos_xyz, rot=(1.0, 0.0, 0.0, 0.0)),
            actuators={
                "all": ImplicitActuatorCfg(
                    joint_names_expr=[".*"], stiffness=float(args.stiffness), damping=float(args.damping)
                )
            },
        )
        return Articulation(cfg)

    # Spawn robots
    robots: dict[str, Articulation] = {}
    if args.hand in ("right", "both"):
        x = +0.5 * float(args.hand_spacing) if args.hand == "both" else 0.0
        robots["right"] = _make_hand("/World/Robot/TriHandRight", hand="right", pos_xyz=(x, 0.0, float(args.spawn_height)))
    if args.hand in ("left", "both"):
        x = -0.5 * float(args.hand_spacing) if args.hand == "both" else 0.0
        robots["left"] = _make_hand("/World/Robot/TriHandLeft", hand="left", pos_xyz=(x, 0.0, float(args.spawn_height)))

    # init
    sim.reset()
    for r in robots.values():
        r.reset()
    sim.step()
    for r in robots.values():
        r.update(sim.get_physics_dt())

    if args.print_body_names:
        for hand, robot in robots.items():
            names = getattr(robot.data, "body_names", None)
            if names is None:
                print(f"[bodies] {hand}: (robot.data.body_names not available)")
            else:
                print(f"[bodies] {hand}: {list(names)}")
        simulation_app.close()
        return

    # Map trajectory DOF names -> robot DOF indices (per hand).
    idxs_by_hand: dict[str, list[int]] = {}
    if "right" in robots:
        robot_names = list(getattr(robots["right"], "joint_names", []))
        name_to_idx = {n: i for i, n in enumerate(robot_names)}
        idxs = []
        missing = []
        assert names_right is not None
        for n in names_right:
            if n not in name_to_idx:
                missing.append(n)
            else:
                idxs.append(int(name_to_idx[n]))
        if missing:
            raise RuntimeError(f"Some RIGHT trajectory joints are missing on the robot: {missing}. Robot has: {robot_names}")
        idxs_by_hand["right"] = idxs

    if "left" in robots:
        robot_names = list(getattr(robots["left"], "joint_names", []))
        name_to_idx = {n: i for i, n in enumerate(robot_names)}
        idxs = []
        missing = []
        assert names_left is not None
        for n in names_left:
            if n not in name_to_idx:
                missing.append(n)
            else:
                idxs.append(int(name_to_idx[n]))
        if missing:
            raise RuntimeError(f"Some LEFT trajectory joints are missing on the robot: {missing}. Robot has: {robot_names}")
        idxs_by_hand["left"] = idxs

    sim_dt = float(sim.get_physics_dt())
    # Determine playback horizon and hold steps.
    if args.hand == "right":
        assert q_right is not None and frame_dt_right is not None
        T = int(q_right.shape[0])
        frame_dt = float(frame_dt_right)
    elif args.hand == "left":
        assert q_left is not None and frame_dt_left is not None
        T = int(q_left.shape[0])
        frame_dt = float(frame_dt_left)
    else:
        assert q_left is not None and q_right is not None and frame_dt_left is not None
        T = int(min(q_left.shape[0], q_right.shape[0]))
        frame_dt = float(frame_dt_left)

    hold_steps = max(int(round((frame_dt / max(float(args.speed), 1e-6)) / sim_dt)), 1)
    print(f"[replay] mode={args.hand} T={T} frame_dt={frame_dt:.4f}s sim_dt={sim_dt:.4f}s hold_steps={hold_steps}")

    # playback loop
    if T <= 0:
        print("[replay][WARN] Empty trajectory (T=0). Nothing to play.")
        simulation_app.close()
        return

    start_frame = int(max(args.start_frame, 0))
    if start_frame >= T:
        raise ValueError(f"--start_frame={start_frame} is out of range for T={T}")

    stop_frame = None if args.stop_frame is None else int(args.stop_frame)
    if stop_frame is not None:
        if stop_frame < 0 or stop_frame >= T:
            raise ValueError(f"--stop_frame={stop_frame} is out of range for T={T}")
        if stop_frame < start_frame:
            raise ValueError(f"--stop_frame ({stop_frame}) must be >= --start_frame ({start_frame})")

    t = start_frame
    while simulation_app.is_running():
        # If user requested a stop frame, hold that pose indefinitely once reached.
        if stop_frame is not None and t >= stop_frame:
            t = stop_frame
        else:
            # Stop after one pass unless looping is requested.
            if t >= T:
                if args.loop and T > 0:
                    t = start_frame
                else:
                    break

        # Optional: world-view wrist/base pose replay.
        # IMPORTANT: also zero root velocity when teleporting, otherwise PhysX can integrate residual
        # velocities during the internal sub-steps (looks like the hands drifting/floating upward).
        root_pose_targets: dict[str, torch.Tensor] = {}
        zero_root_vel: dict[str, torch.Tensor] = {}
        if args.use_wrist_pose:
            env_ids = None
            if "right" in robots:
                wr = extras_right.get("right_wrist", None)
                if wr is not None and wr.shape[0] > t:
                    # IMPORTANT: copy so offsets/rotations don't mutate the underlying trajectory array
                    # (otherwise holding a frame would accumulate offsets every sim step).
                    pose = np.asarray(wr[t], dtype=np.float32).reshape(7).copy()
                    pose[2] += float(args.wrist_z_offset)
                    pose = _apply_wrist_pose_rot(pose, hand="right")
                    if not args.suggest_wrist_to_root_offset:
                        pose = _apply_wrist_to_root_offset(pose, hand="right")
                    root_pose_targets["right"] = torch.tensor(pose[None, :], device=robots["right"].data.device)
                    zero_root_vel["right"] = torch.zeros((1, 6), device=robots["right"].data.device, dtype=torch.float32)
            if "left" in robots:
                wl = extras_left.get("left_wrist", None)
                if wl is not None and wl.shape[0] > t:
                    # IMPORTANT: copy so offsets/rotations don't mutate the underlying trajectory array.
                    pose = np.asarray(wl[t], dtype=np.float32).reshape(7).copy()
                    pose[2] += float(args.wrist_z_offset)
                    pose = _apply_wrist_pose_rot(pose, hand="left")
                    if not args.suggest_wrist_to_root_offset:
                        pose = _apply_wrist_to_root_offset(pose, hand="left")
                    root_pose_targets["left"] = torch.tensor(pose[None, :], device=robots["left"].data.device)
                    zero_root_vel["left"] = torch.zeros((1, 6), device=robots["left"].data.device, dtype=torch.float32)

        # Build full DOF target vector(s) (1 env each) and apply.
        targets: dict[str, torch.Tensor] = {}
        for hand, robot in robots.items():
            target = torch.zeros((1, robot.num_joints), device=robot.data.device, dtype=torch.float32)
            idxs = idxs_by_hand[hand]
            if hand == "right":
                assert q_right is not None
                q = q_right[t]
            else:
                assert q_left is not None
                q = q_left[t]
            for j, ridx in enumerate(idxs):
                target[0, int(ridx)] = float(q[j])
            targets[hand] = target

        # snap once at the start
        if t == 0:
            for hand, robot in robots.items():
                robot.write_joint_position_to_sim(targets[hand])

        # Apply targets and step sim
        for hand, robot in robots.items():
            robot.set_joint_position_target(targets[hand])
        for _ in range(hold_steps):
            # Re-apply root pose + zero velocity on every physics step (prevents drift).
            if args.use_wrist_pose:
                for hand, robot in robots.items():
                    if hand in root_pose_targets:
                        robot.write_root_pose_to_sim(root_pose_targets[hand], env_ids=None)
                        robot.write_root_link_velocity_to_sim(zero_root_vel[hand], env_ids=None)
            for robot in robots.values():
                robot.write_data_to_sim()
            sim.step()
            for robot in robots.values():
                robot.update(sim_dt)

            # Suggest offsets once, after at least one physics step with the root pose written.
            if args.suggest_wrist_to_root_offset and args.use_wrist_pose and stop_frame is not None and t == stop_frame:
                for hand, robot in robots.items():
                    if hand not in root_pose_targets:
                        continue
                    tgt = root_pose_targets[hand].detach().cpu().numpy().reshape(7).astype(np.float32)
                    p_tgt = tgt[:3]
                    q_tgt = tgt[3:]

                    want = args.suggest_link_left if hand == "left" else args.suggest_link_right
                    body_names = list(getattr(robot.data, "body_names", []))
                    if want not in body_names:
                        print(f"[suggest][{hand}] link '{want}' not found. Available={body_names}")
                        continue
                    idx = int(body_names.index(want))
                    p_body = robot.data.body_pos_w[0, idx].detach().cpu().numpy().astype(np.float32)

                    v_world = (p_tgt - p_body).astype(np.float32)
                    off = _quat_apply_wxyz(_quat_inv_wxyz(q_tgt), v_world)
                    print(
                        f"[suggest][{hand}] link='{want}' p_tgt={p_tgt.tolist()} p_body={p_body.tolist()} "
                        f"v_world=(p_tgt-p_body)={v_world.tolist()} => wrist_to_root_offset_{hand}={off.tolist()}"
                    )

                print("[suggest] Done. Re-run with the printed --wrist_to_root_offset_left/right values.")
                simulation_app.close()
                return
        # Advance unless holding at stop frame.
        if stop_frame is None or t < stop_frame:
            t += 1

    simulation_app.close()


if __name__ == "__main__":
    main()


