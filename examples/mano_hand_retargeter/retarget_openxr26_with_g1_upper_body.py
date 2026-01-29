#!/usr/bin/env python3
"""
Retarget transformed OpenXR-26 joints to Unitree G1 upper-body commands (offline, no Isaac Sim).

Why this exists
---------------
IsaacLab's `G1TriHandUpperBodyRetargeter` (and the OpenXR package) transitively imports Omniverse USD
(`pxr`) and `carb/omni.client`. In a plain Python environment you may not have these modules, which
causes import failures like:

  ModuleNotFoundError: No module named 'pxr'

This script implements the *same* core logic as IsaacLab's G1 tri-hand dex retargeting utility,
but without importing `isaaclab` at all. It only depends on:
  - numpy
  - torch
  - scipy
  - pyyaml
  - dex_retargeting (+ pinocchio)

Inputs
------
- Your `.npz` frame files must contain OpenXR-26 joint positions for left/right hands as float arrays
  shaped (26, 3), using OpenXR joint ordering.

Output command layout (matches IsaacLab's upper-body retargeter layout)
----------------------------------------------------------------------
- [0:7]   left wrist pose in USD control frame  (x,y,z,qw,qx,qy,qz)
- [7:14]  right wrist pose in USD control frame (x,y,z,qw,qx,qy,qz)
- [14:]   hand joint angles in the dex-retargeting DOF order (names saved alongside)
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional, Tuple


# OpenXR-26 joint ordering (IsaacLab's `isaaclab.devices.openxr.common.HAND_JOINT_NAMES`).
HAND_JOINT_NAMES = [
    "palm",
    "wrist",
    "thumb_metacarpal",
    "thumb_proximal",
    "thumb_distal",
    "thumb_tip",
    "index_metacarpal",
    "index_proximal",
    "index_intermediate",
    "index_distal",
    "index_tip",
    "middle_metacarpal",
    "middle_proximal",
    "middle_intermediate",
    "middle_distal",
    "middle_tip",
    "ring_metacarpal",
    "ring_proximal",
    "ring_intermediate",
    "ring_distal",
    "ring_tip",
    "little_metacarpal",
    "little_proximal",
    "little_intermediate",
    "little_distal",
    "little_tip",
]

# Map OpenXR-26 joints to the 21 joints used in dex-retargeting (IsaacLab).
_HAND_JOINTS_INDEX = [1, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14, 15, 17, 18, 19, 20, 22, 23, 24, 25]

# Canonical-frame conversion (IsaacLab `g1_dex_retargeting_utils.py`).
_OPERATOR2MANO_RIGHT = [
    [0, 0, 1],
    [1, 0, 0],
    [0, 1, 0],
]
_OPERATOR2MANO_LEFT = [
    [0, 0, 1],
    [1, 0, 0],
    [0, 1, 0],
]

# Wrist conversion quaternions used by IsaacLab `G1TriHandUpperBodyRetargeter._retarget_abs`.
_LEFT_WRIST_COMBINED_QUAT_WXYZ = (0.7071, 0.0, 0.7071, 0.0)
_RIGHT_WRIST_COMBINED_QUAT_WXYZ = (0.0, -0.7071, 0.0, 0.7071)


# -----------------------------
# Visualization helpers (ported from IsaacLab's `g1_dex_retargeting_utils.py`)
# -----------------------------

_OPENPOSE21_EDGES = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),  # thumb
    (0, 5),
    (5, 6),
    (6, 7),
    (7, 8),  # index
    (0, 9),
    (9, 10),
    (10, 11),
    (11, 12),  # middle
    (0, 13),
    (13, 14),
    (14, 15),
    (15, 16),  # ring
    (0, 17),
    (17, 18),
    (18, 19),
    (19, 20),  # little
]

_OPENPOSE21_FINGERS = {
    "root": [0],
    "thumb": [1, 2, 3, 4],
    "index": [5, 6, 7, 8],
    "middle": [9, 10, 11, 12],
    "ring": [13, 14, 15, 16],
    "little": [17, 18, 19, 20],
}

_FINGER_COLORS = {
    "root": (0.55, 0.55, 0.55),
    "thumb": (0.90, 0.20, 0.20),
    "index": (0.20, 0.60, 0.95),
    "middle": (0.20, 0.75, 0.30),
    "ring": (0.90, 0.55, 0.15),
    "little": (0.75, 0.30, 0.85),
}


def _colors_lighter_with_y(points_xyz, base_rgb, strength: float = 0.65):
    import numpy as np

    pts = np.asarray(points_xyz, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"points_xyz must be (N,3); got {pts.shape}")
    y = pts[:, 1]
    denom = float(np.max(y) - np.min(y))
    if denom < 1e-8:
        t = np.zeros_like(y)
    else:
        t = (y - float(np.min(y))) / (denom + 1e-8)
    t = np.clip(t * float(strength), 0.0, 1.0)[:, None]
    base = np.asarray(base_rgb, dtype=np.float32)[None, :]
    white = np.ones((1, 3), dtype=np.float32)
    return (base * (1.0 - t) + white * t).clip(0.0, 1.0)


def _joint_to_finger_openpose21(j: int) -> str:
    for k, idxs in _OPENPOSE21_FINGERS.items():
        if j in idxs:
            return k
    return "root"


def _lazy_import_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _append_text(path: Path, msg: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def _plot_openxr26_joints(joints26, *, out_path: Path, title: str):
    """
    Simple OpenXR-26 visualization: point cloud + labels for wrist + tips.
    """
    import numpy as np

    joints26 = np.asarray(joints26, dtype=np.float32)
    if joints26.shape != (26, 3):
        return
    plt = _lazy_import_matplotlib()
    fig = plt.figure(figsize=(7.2, 6.2), dpi=160)
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(joints26[:, 0], joints26[:, 1], joints26[:, 2], s=18, c="tab:blue", alpha=0.9)
    # label wrist and tips
    for name in ["wrist", "thumb_tip", "index_tip", "middle_tip", "ring_tip", "little_tip"]:
        if name in HAND_JOINT_NAMES:
            i = HAND_JOINT_NAMES.index(name)
            x, y, z = joints26[i]
            ax.text(x, y, z, f"{name} (y={y:+.3f})" if "tip" in name else name, fontsize=8, color="black")
            ax.plot([x, x], [y, 0.0], [z, z], c="black", linewidth=1.0, alpha=0.25, linestyle=":")
    ax.set_title(title)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.view_init(elev=20, azim=-60)
    mins = joints26.min(axis=0)
    maxs = joints26.max(axis=0)
    center = 0.5 * (mins + maxs)
    radius = 0.5 * float(np.max(maxs - mins) + 1e-6)
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path))
    plt.close(fig)


def _plot_joint_pos_openpose21(
    joint_pos,
    *,
    out_path: Path,
    title: str,
    ref_value=None,
    human_indices=None,
    retargeting_type: Optional[str] = None,
):
    import numpy as np

    joint_pos = np.asarray(joint_pos, dtype=np.float32)
    if joint_pos.shape != (21, 3):
        return
    plt = _lazy_import_matplotlib()
    fig = plt.figure(figsize=(7.2, 6.2), dpi=160)
    ax = fig.add_subplot(111, projection="3d")

    for finger, idxs in _OPENPOSE21_FINGERS.items():
        pts = joint_pos[idxs]
        cols = _colors_lighter_with_y(pts, _FINGER_COLORS.get(finger, (0.3, 0.3, 0.3)))
        ax.scatter(
            pts[:, 0],
            pts[:, 1],
            pts[:, 2],
            s=30 if finger == "root" else 22,
            c=cols,
            label=finger,
        )

    for a, b in _OPENPOSE21_EDGES:
        finger = _joint_to_finger_openpose21(int(b))
        ax.plot(
            [joint_pos[a, 0], joint_pos[b, 0]],
            [joint_pos[a, 1], joint_pos[b, 1]],
            [joint_pos[a, 2], joint_pos[b, 2]],
            linewidth=2.0,
            alpha=0.9,
            c=_FINGER_COLORS.get(finger, (0.2, 0.2, 0.2)),
        )

    # fingertips labels
    tip_ids = [4, 8, 12, 16, 20]
    tip_names = ["thumb_tip", "index_tip", "middle_tip", "ring_tip", "little_tip"]
    y_label_tips = {"thumb_tip", "index_tip", "middle_tip"}
    for i, name in zip(tip_ids, tip_names):
        x, y, z = joint_pos[i]
        label = f"{name} (y={y:+.3f})" if name in y_label_tips else name
        ax.text(x, y, z, label, fontsize=8, color="black")
        ax.plot([x, x], [y, 0.0], [z, z], c="black", linewidth=1.0, alpha=0.35, linestyle=":")

    # Draw ref_value as overlay (POSITION: target points; VECTOR: dashed vectors)
    if ref_value is not None and human_indices is not None and retargeting_type is not None:
        ref_value = np.asarray(ref_value, dtype=np.float32)
        human_indices = np.asarray(human_indices)
        rtype = str(retargeting_type).upper()
        if rtype == "POSITION":
            idxs = human_indices.reshape(-1).astype(int)
            idxs = idxs[(idxs >= 0) & (idxs < joint_pos.shape[0])]
            if idxs.size > 0:
                ax.scatter(
                    joint_pos[idxs, 0],
                    joint_pos[idxs, 1],
                    joint_pos[idxs, 2],
                    s=70,
                    marker="x",
                    c="black",
                    label="ref_value (pos targets)",
                )
        else:
            if human_indices.ndim == 2 and human_indices.shape[0] == 2:
                origin = human_indices[0].astype(int)
                task = human_indices[1].astype(int)
                n = min(len(origin), len(task), ref_value.shape[0])
                for k in range(n):
                    a = int(origin[k])
                    b = int(task[k])
                    if not (0 <= a < joint_pos.shape[0] and 0 <= b < joint_pos.shape[0]):
                        continue
                    p0 = joint_pos[a]
                    p1 = p0 + ref_value[k]
                    ax.plot(
                        [p0[0], p1[0]],
                        [p0[1], p1[1]],
                        [p0[2], p1[2]],
                        linewidth=1.5,
                        alpha=0.8,
                        c="black",
                        linestyle="--",
                    )

    ax.set_title(title)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.view_init(elev=20, azim=-60)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 1.0))

    mins = joint_pos.min(axis=0)
    maxs = joint_pos.max(axis=0)
    center = 0.5 * (mins + maxs)
    radius = 0.5 * float(np.max(maxs - mins) + 1e-6)
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(str(out_path))
    plt.close(fig)


def _extract_robot_points_for_optimizer(optimizer, robot_qpos):
    import numpy as np

    robot = optimizer.robot
    robot.compute_forward_kinematics(robot_qpos)

    link_names = None
    link_indices = None
    if hasattr(optimizer, "computed_link_names") and hasattr(optimizer, "computed_link_indices"):
        link_names = list(getattr(optimizer, "computed_link_names"))
        link_indices = list(getattr(optimizer, "computed_link_indices"))
    elif hasattr(optimizer, "body_names") and hasattr(optimizer, "target_link_indices"):
        link_names = list(getattr(optimizer, "body_names"))
        link_indices = list(getattr(optimizer, "target_link_indices"))
    else:
        link_names, link_indices = [], []

    pts = []
    for idx in link_indices:
        pose = robot.get_link_pose(int(idx))
        pts.append(pose[:3, 3])
    pts = np.asarray(pts, dtype=np.float32) if pts else np.zeros((0, 3), dtype=np.float32)
    return link_names, link_indices, pts


def _proxy_loss_from_optimizer(optimizer, *, ref_value, robot_qpos) -> Optional[float]:
    """
    Best-effort "loss" estimate from geometry (works even if dex_retargeting doesn't expose loss history).
    """
    import numpy as np

    ref_value = np.asarray(ref_value, dtype=np.float32)
    robot_qpos = np.asarray(robot_qpos, dtype=np.float32).reshape(-1)

    rtype = str(getattr(optimizer, "retargeting_type", "")).upper()
    link_names, link_indices, pts = _extract_robot_points_for_optimizer(optimizer, robot_qpos)
    if pts.shape[0] == 0:
        return None

    if rtype == "POSITION":
        # Target link positions vs ref_value positions
        if not hasattr(optimizer, "target_link_indices"):
            return None
        idxs = np.asarray(getattr(optimizer, "target_link_indices")).astype(int).reshape(-1)
        n = min(len(idxs), ref_value.shape[0], pts.shape[0])
        if n <= 0:
            return None
        # `pts` already corresponds to `link_indices`, not necessarily `target_link_indices`.
        # If computed_link_indices equals target_link_indices, this is consistent; otherwise best-effort.
        err = pts[:n] - ref_value[:n]
        return float(np.mean(np.sum(err * err, axis=-1)))

    # VECTOR / DexPilot style: robot vectors (task-origin) vs ref_value vectors
    if not (hasattr(optimizer, "origin_link_indices") and hasattr(optimizer, "task_link_indices")):
        return None
    origin_idx = np.asarray(getattr(optimizer, "origin_link_indices")).astype(int).reshape(-1)
    task_idx = np.asarray(getattr(optimizer, "task_link_indices")).astype(int).reshape(-1)
    n = min(len(origin_idx), len(task_idx), ref_value.shape[0])
    if n <= 0:
        return None

    # Here origin/task indices are into the robot's link set used by optimizer; often matches `computed_link_indices`.
    # We interpret them as indices into `pts` if that seems valid; otherwise can't compute.
    if np.max(origin_idx[:n]) >= pts.shape[0] or np.max(task_idx[:n]) >= pts.shape[0]:
        return None
    robot_vec = pts[task_idx[:n]] - pts[origin_idx[:n]]
    err = robot_vec - ref_value[:n]
    return float(np.mean(np.sum(err * err, axis=-1)))


def _plot_robot_links(robot_qpos, *, optimizer, out_path: Path, title: str):
    import numpy as np

    robot_qpos = np.asarray(robot_qpos, dtype=np.float32).reshape(-1)
    link_names, link_indices, pts = _extract_robot_points_for_optimizer(optimizer, robot_qpos)
    if pts.shape[0] == 0:
        return
    plt = _lazy_import_matplotlib()
    fig = plt.figure(figsize=(7.2, 6.2), dpi=160)
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2], s=28, c="tab:orange")
    for i, name in enumerate(link_names):
        if name == "base_link" or "tip" in name:
            ax.text(pts[i, 0], pts[i, 1], pts[i, 2], f"{name} (y={pts[i, 1]:+.3f})", fontsize=8, color="black")
    ax.set_title(title)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.view_init(elev=20, azim=-60)
    mins = pts.min(axis=0)
    maxs = pts.max(axis=0)
    center = 0.5 * (mins + maxs)
    radius = 0.5 * float(np.max(maxs - mins) + 1e-6)
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(str(out_path))
    plt.close(fig)


def _plot_combined_scene(
    joint_pos,
    *,
    ref_value,
    human_indices,
    retargeting_type: str,
    optimizer,
    robot_qpos,
    out_path: Path,
    title: str,
):
    import numpy as np

    joint_pos = np.asarray(joint_pos, dtype=np.float32)
    ref_value = np.asarray(ref_value, dtype=np.float32)
    human_indices = np.asarray(human_indices)
    robot_qpos = np.asarray(robot_qpos, dtype=np.float32).reshape(-1)
    if joint_pos.shape != (21, 3):
        return

    plt = _lazy_import_matplotlib()
    fig = plt.figure(figsize=(7.8, 6.8), dpi=160)
    ax = fig.add_subplot(111, projection="3d")

    # Human
    for finger, idxs in _OPENPOSE21_FINGERS.items():
        pts = joint_pos[idxs]
        cols = _colors_lighter_with_y(pts, _FINGER_COLORS.get(finger, (0.3, 0.3, 0.3)))
        ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2], s=30 if finger == "root" else 22, c=cols, alpha=0.95)
    for a, b in _OPENPOSE21_EDGES:
        finger = _joint_to_finger_openpose21(int(b))
        ax.plot(
            [joint_pos[a, 0], joint_pos[b, 0]],
            [joint_pos[a, 1], joint_pos[b, 1]],
            [joint_pos[a, 2], joint_pos[b, 2]],
            linewidth=2.0,
            alpha=0.65,
            c=_FINGER_COLORS.get(finger, (0.2, 0.2, 0.2)),
        )
    # Ref vectors (vector mode)
    rtype = str(retargeting_type).upper()
    if rtype != "POSITION" and human_indices.ndim == 2 and human_indices.shape[0] == 2:
        origin = human_indices[0].astype(int)
        task = human_indices[1].astype(int)
        n = min(len(origin), len(task), ref_value.shape[0])
        for k in range(n):
            a = int(origin[k])
            b = int(task[k])
            if not (0 <= a < joint_pos.shape[0] and 0 <= b < joint_pos.shape[0]):
                continue
            p0 = joint_pos[a]
            p1 = p0 + ref_value[k]
            ax.plot([p0[0], p1[0]], [p0[1], p1[1]], [p0[2], p1[2]], c="black", lw=1.4, alpha=0.9, ls="--")

    # Robot
    link_names, link_indices, pts = _extract_robot_points_for_optimizer(optimizer, robot_qpos)
    if pts.shape[0] > 0:
        ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2], s=34, c="tab:orange", alpha=0.95)
        # robot vectors (if exposed)
        if hasattr(optimizer, "origin_link_indices") and hasattr(optimizer, "task_link_indices") and hasattr(
            optimizer, "num_fingers"
        ):
            origin_idx = np.asarray(getattr(optimizer, "origin_link_indices")).astype(int).reshape(-1)
            task_idx = np.asarray(getattr(optimizer, "task_link_indices")).astype(int).reshape(-1)
            n = min(len(origin_idx), len(task_idx), ref_value.shape[0])
            num_fingers = int(getattr(optimizer, "num_fingers"))
            base_start = max(0, n - num_fingers)
            if np.max(origin_idx[:n]) < pts.shape[0] and np.max(task_idx[:n]) < pts.shape[0]:
                for k in range(n):
                    a = int(origin_idx[k])
                    b = int(task_idx[k])
                    p0 = pts[a]
                    p1 = pts[b]
                    if k >= base_start:
                        c = "tab:orange"
                        lw = 2.2
                        al = 0.85
                    else:
                        c = "tab:gray"
                        lw = 1.4
                        al = 0.6
                    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], [p0[2], p1[2]], c=c, lw=lw, alpha=al)

    ax.set_title(title)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.view_init(elev=20, azim=-60)

    # Equal-ish axis across both sets
    all_pts = [joint_pos]
    if pts.shape[0] > 0:
        all_pts.append(pts)
    all_pts = np.concatenate(all_pts, axis=0)
    mins = all_pts.min(axis=0)
    maxs = all_pts.max(axis=0)
    center = 0.5 * (mins + maxs)
    radius = 0.5 * float(np.max(maxs - mins) + 1e-6)
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(str(out_path))
    plt.close(fig)


def _plot_loss_summary(*, out_path: Path, title: str, init_loss: Optional[float], opt_loss: Optional[float]):
    plt = _lazy_import_matplotlib()
    fig = plt.figure(figsize=(6.0, 3.2), dpi=160)
    ax = fig.add_subplot(111)
    xs = [0, 1]
    ys = [init_loss if init_loss is not None else 0.0, opt_loss if opt_loss is not None else 0.0]
    ax.bar(xs, ys, color=["tab:gray", "tab:orange"])
    ax.set_xticks(xs, ["init", "opt"])
    ax.set_title(title)
    ax.set_ylabel("proxy loss (mean squared error)")
    if init_loss is not None:
        ax.text(0, ys[0], f"{ys[0]:.4g}", ha="center", va="bottom", fontsize=9)
    if opt_loss is not None:
        ax.text(1, ys[1], f"{ys[1]:.4g}", ha="center", va="bottom", fontsize=9)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(str(out_path))
    plt.close(fig)


def _parse_float_list(csv: str) -> list[float]:
    parts = [p.strip() for p in str(csv).split(",") if p.strip() != ""]
    return [float(p) for p in parts]


def _rotate_openxr26_xyz(joints26_xyz, *, euler_xyz_deg: tuple[float, float, float], pivot: str = "wrist"):
    """
    Apply an XYZ Euler rotation (degrees) to OpenXR-26 joint positions.

    Rotation is applied about:
      - 'wrist' (default): joint index for 'wrist'
      - 'palm': joint index for 'palm'
      - 'origin': (0,0,0)
    """
    import numpy as np
    from scipy.spatial.transform import Rotation as R

    joints = np.asarray(joints26_xyz, dtype=np.float32)
    if joints.shape != (26, 3):
        raise ValueError(f"Expected joints26_xyz shape (26,3), got {joints.shape}")

    rot = R.from_euler("xyz", list(euler_xyz_deg), degrees=True).as_matrix().astype(np.float32)

    pv = str(pivot).lower().strip()
    if pv == "origin":
        center = np.zeros((1, 3), dtype=np.float32)
    elif pv == "palm":
        center = joints[HAND_JOINT_NAMES.index("palm") : HAND_JOINT_NAMES.index("palm") + 1]
    else:
        center = joints[HAND_JOINT_NAMES.index("wrist") : HAND_JOINT_NAMES.index("wrist") + 1]

    # row-vector convention: p' = (p-center) @ R^T + center
    return (joints - center) @ rot.T + center


def _grid_search_rotations(
    *,
    controller: "_StandaloneDexTriHandRetargeter",
    hand: str,
    openxr26_xyz,  # for single-file mode
    tag_base: str,  # for single-file mode
    out_dir: Path,
    angles_deg: list[float],
    pivot: str,
    topk_viz: int = 0,
) -> Path:
    """
    Grid-search XYZ Euler rotations and compare proxy loss after optimization.
    Writes a CSV sorted by opt_loss (ascending). Returns the CSV path.
    """
    import csv
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    hand = str(hand).lower().strip()
    if hand not in ("left", "right"):
        raise ValueError("--grid-hand must be 'left' or 'right'")

    # Choose retargeting objects
    retargeting = controller._dex_left_hand if hand == "left" else controller._dex_right_hand  # noqa: SLF001
    operator2mano = _OPERATOR2MANO_LEFT if hand == "left" else _OPERATOR2MANO_RIGHT

    # Cache init qpos for fair resets (if supported).
    init_qpos0 = None
    try:
        if hasattr(retargeting, "get_qpos"):
            init_qpos0 = np.asarray(retargeting.get_qpos(), dtype=np.float32).reshape(-1)
    except Exception:
        init_qpos0 = None

    def maybe_reset_qpos():
        if init_qpos0 is None:
            return
        if hasattr(retargeting, "set_qpos"):
            try:
                retargeting.set_qpos(init_qpos0)
            except Exception:
                pass

    rows = []
    # Evaluate all combos
    for ax in angles_deg:
        for ay in angles_deg:
            for az in angles_deg:
                maybe_reset_qpos()
                xyz_rot = _rotate_openxr26_xyz(openxr26_xyz, euler_xyz_deg=(ax, ay, az), pivot=pivot)
                pose_dict = openxr26_positions_to_pose_dict(xyz_rot)
                joint_pos = controller.convert_hand_joints(pose_dict, operator2mano)
                ref_value = controller.compute_ref_value(
                    joint_pos,
                    indices=retargeting.optimizer.target_link_human_indices,
                    retargeting_type=str(retargeting.optimizer.retargeting_type),
                )

                init_loss = None
                if init_qpos0 is not None:
                    init_loss = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=init_qpos0)

                # Optimize
                try:
                    import torch

                    with torch.enable_grad():
                        with torch.inference_mode(False):
                            robot_qpos = retargeting.retarget(ref_value)
                except Exception:
                    robot_qpos = retargeting.retarget(ref_value)

                opt_loss = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=robot_qpos)
                rows.append(
                    {
                        "x_deg": float(ax),
                        "y_deg": float(ay),
                        "z_deg": float(az),
                        "init_loss": float(init_loss) if init_loss is not None else "",
                        "opt_loss": float(opt_loss) if opt_loss is not None else "",
                    }
                )

    # Sort and write CSV
    def sort_key(r):
        v = r["opt_loss"]
        return float(v) if v != "" else float("inf")

    rows_sorted = sorted(rows, key=sort_key)
    csv_path = out_dir / f"{tag_base}__{hand}__rot_grid_search.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["x_deg", "y_deg", "z_deg", "init_loss", "opt_loss"])
        w.writeheader()
        w.writerows(rows_sorted)

    # Optional: visualize best K (human+robot+loss) to sanity check.
    if topk_viz > 0:
        best = rows_sorted[: max(int(topk_viz), 0)]
        for i, r in enumerate(best):
            ax, ay, az = float(r["x_deg"]), float(r["y_deg"]), float(r["z_deg"])
            maybe_reset_qpos()
            xyz_rot = _rotate_openxr26_xyz(openxr26_xyz, euler_xyz_deg=(ax, ay, az), pivot=pivot)
            pose_dict = openxr26_positions_to_pose_dict(xyz_rot)
            joint_pos = controller.convert_hand_joints(pose_dict, operator2mano)
            ref_value = controller.compute_ref_value(
                joint_pos,
                indices=retargeting.optimizer.target_link_human_indices,
                retargeting_type=str(retargeting.optimizer.retargeting_type),
            )
            init_qpos = init_qpos0 if init_qpos0 is not None else None
            try:
                import torch

                with torch.enable_grad():
                    with torch.inference_mode(False):
                        robot_qpos = retargeting.retarget(ref_value)
            except Exception:
                robot_qpos = retargeting.retarget(ref_value)

            tag = f"{tag_base}__{hand}__best{i:02d}__x{ax:+.0f}_y{ay:+.0f}_z{az:+.0f}"
            _plot_openxr26_joints(xyz_rot, out_path=out_dir / f"{tag}__openxr26_rot.png", title=f"OpenXR26 (rot): {tag}")
            _plot_joint_pos_openpose21(
                joint_pos,
                out_path=out_dir / f"{tag}__human_openpose21_preopt.png",
                title=f"Human pre-opt (rot): {tag}",
                ref_value=ref_value,
                human_indices=retargeting.optimizer.target_link_human_indices,
                retargeting_type=str(retargeting.optimizer.retargeting_type),
            )
            if init_qpos is not None:
                _plot_combined_scene(
                    joint_pos,
                    ref_value=ref_value,
                    human_indices=retargeting.optimizer.target_link_human_indices,
                    retargeting_type=str(retargeting.optimizer.retargeting_type),
                    optimizer=retargeting.optimizer,
                    robot_qpos=init_qpos,
                    out_path=out_dir / f"{tag}__combined_init.png",
                    title=f"Human+Robot init (rot): {tag}",
                )
            _plot_combined_scene(
                joint_pos,
                ref_value=ref_value,
                human_indices=retargeting.optimizer.target_link_human_indices,
                retargeting_type=str(retargeting.optimizer.retargeting_type),
                optimizer=retargeting.optimizer,
                robot_qpos=robot_qpos,
                out_path=out_dir / f"{tag}__combined_opt.png",
                title=f"Human+Robot opt (rot): {tag}",
            )
            init_loss = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=init_qpos) if init_qpos is not None else None
            opt_loss = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=robot_qpos)
            _plot_loss_summary(
                out_path=out_dir / f"{tag}__loss.png",
                title=f"Proxy loss (rot): {tag}",
                init_loss=init_loss,
                opt_loss=opt_loss,
            )

    return csv_path


def _grid_search_rotations_multi(
    *,
    controller: "_StandaloneDexTriHandRetargeter",
    hand: str,
    frame_paths: list[Path],
    tag_base: str,
    out_dir: Path,
    angles_deg: list[float],
    pivot: str,
    step: int = 10,
    max_frames: Optional[int] = None,
    topk_viz: int = 0,
    left_key: Optional[str] = None,
    right_key: Optional[str] = None,
    lr_key_2x26x3: Optional[str] = None,
    single_hand: Optional[str] = None,
) -> Path:
    """
    Multi-frame rotation grid search:
      - samples `frame_paths[::step]` (and optionally truncates to `max_frames`)
      - ranks rotations by aggregate opt loss across sampled frames
      - writes a summary CSV sorted by mean_opt_loss
    """
    import csv
    import numpy as np
    from scipy.spatial.transform import Rotation as R

    out_dir.mkdir(parents=True, exist_ok=True)
    hand = str(hand).lower().strip()
    if hand not in ("left", "right"):
        raise ValueError("--grid-hand must be 'left' or 'right'")
    step = max(int(step), 1)

    # sample frames
    sampled = frame_paths[::step]
    if max_frames is not None:
        sampled = sampled[: max(int(max_frames), 0)]
    if not sampled:
        raise ValueError("No frames selected for multi-frame grid search")

    # Choose retargeting objects
    retargeting = controller._dex_left_hand if hand == "left" else controller._dex_right_hand  # noqa: SLF001
    operator2mano = _OPERATOR2MANO_LEFT if hand == "left" else _OPERATOR2MANO_RIGHT

    # Cache initial qpos for fair resets (if supported).
    init_qpos0 = None
    try:
        if hasattr(retargeting, "get_qpos"):
            init_qpos0 = np.asarray(retargeting.get_qpos(), dtype=np.float32).reshape(-1)
    except Exception:
        init_qpos0 = None

    def maybe_reset_qpos():
        if init_qpos0 is None:
            return
        if hasattr(retargeting, "set_qpos"):
            try:
                retargeting.set_qpos(init_qpos0)
            except Exception:
                pass

    # Precompute rotation matrices for all combos.
    combos: list[tuple[float, float, float, np.ndarray]] = []
    for ax in angles_deg:
        for ay in angles_deg:
            for az in angles_deg:
                mat = R.from_euler("xyz", [ax, ay, az], degrees=True).as_matrix().astype(np.float32)
                combos.append((float(ax), float(ay), float(az), mat))

    # Evaluate: for each combo, accumulate losses across frames.
    summary_rows = []
    for ax, ay, az, rot in combos:
        losses = []
        init_losses = []
        n_used = 0

        for p in sampled:
            left_xyz, right_xyz, _, _, _ = _load_openxr26_from_npz(
                p,
                left_key=left_key,
                right_key=right_key,
                lr_key_2x26x3=lr_key_2x26x3,
                single_hand=single_hand,
            )
            xyz = left_xyz if hand == "left" else right_xyz
            if xyz is None:
                continue

            # Rotate about pivot
            joints = np.asarray(xyz, dtype=np.float32)
            pv = str(pivot).lower().strip()
            if pv == "origin":
                center = np.zeros((1, 3), dtype=np.float32)
            elif pv == "palm":
                center = joints[HAND_JOINT_NAMES.index("palm") : HAND_JOINT_NAMES.index("palm") + 1]
            else:
                center = joints[HAND_JOINT_NAMES.index("wrist") : HAND_JOINT_NAMES.index("wrist") + 1]
            joints_rot = (joints - center) @ rot.T + center

            pose_dict = openxr26_positions_to_pose_dict(joints_rot)
            joint_pos = controller.convert_hand_joints(pose_dict, operator2mano)
            ref_value = controller.compute_ref_value(
                joint_pos,
                indices=retargeting.optimizer.target_link_human_indices,
                retargeting_type=str(retargeting.optimizer.retargeting_type),
            )

            if init_qpos0 is not None:
                init_l = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=init_qpos0)
                if init_l is not None:
                    init_losses.append(float(init_l))

            maybe_reset_qpos()
            try:
                import torch

                with torch.enable_grad():
                    with torch.inference_mode(False):
                        robot_qpos = retargeting.retarget(ref_value)
            except Exception:
                robot_qpos = retargeting.retarget(ref_value)

            opt_l = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=robot_qpos)
            if opt_l is None:
                continue
            losses.append(float(opt_l))
            n_used += 1

        if n_used == 0:
            continue
        arr = np.asarray(losses, dtype=np.float32)
        init_arr = np.asarray(init_losses, dtype=np.float32) if init_losses else None
        summary_rows.append(
            {
                "x_deg": ax,
                "y_deg": ay,
                "z_deg": az,
                "n_frames": int(n_used),
                "mean_opt_loss": float(np.mean(arr)),
                "median_opt_loss": float(np.median(arr)),
                "std_opt_loss": float(np.std(arr)),
                "mean_init_loss": float(np.mean(init_arr)) if init_arr is not None else "",
            }
        )

    # sort and write summary
    summary_rows = sorted(summary_rows, key=lambda r: float(r["mean_opt_loss"]))
    csv_path = out_dir / f"{tag_base}__{hand}__rot_grid_search_multiframe.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "x_deg",
                "y_deg",
                "z_deg",
                "n_frames",
                "mean_opt_loss",
                "median_opt_loss",
                "std_opt_loss",
                "mean_init_loss",
            ],
        )
        w.writeheader()
        w.writerows(summary_rows)

    # Optional: visualize best K rotations on the first sampled frame (representative).
    if topk_viz > 0 and summary_rows:
        first_frame = sampled[0]
        left_xyz, right_xyz, _, _, _ = _load_openxr26_from_npz(
            first_frame,
            left_key=left_key,
            right_key=right_key,
            lr_key_2x26x3=lr_key_2x26x3,
            single_hand=single_hand,
        )
        xyz0 = left_xyz if hand == "left" else right_xyz
        if xyz0 is not None:
            best = summary_rows[: max(int(topk_viz), 0)]
            for i, r in enumerate(best):
                ax, ay, az = float(r["x_deg"]), float(r["y_deg"]), float(r["z_deg"])
                tag = f"{tag_base}__{hand}__best{i:02d}__x{ax:+.0f}_y{ay:+.0f}_z{az:+.0f}__frame{first_frame.stem}"
                # Reuse single-file viz path by calling the single-file grid helper's viz path building
                # (implemented inline here for clarity).
                from scipy.spatial.transform import Rotation as R2

                rot = R2.from_euler("xyz", [ax, ay, az], degrees=True).as_matrix().astype(np.float32)
                joints = np.asarray(xyz0, dtype=np.float32)
                pv = str(pivot).lower().strip()
                if pv == "origin":
                    center = np.zeros((1, 3), dtype=np.float32)
                elif pv == "palm":
                    center = joints[HAND_JOINT_NAMES.index("palm") : HAND_JOINT_NAMES.index("palm") + 1]
                else:
                    center = joints[HAND_JOINT_NAMES.index("wrist") : HAND_JOINT_NAMES.index("wrist") + 1]
                joints_rot = (joints - center) @ rot.T + center

                pose_dict = openxr26_positions_to_pose_dict(joints_rot)
                joint_pos = controller.convert_hand_joints(pose_dict, operator2mano)
                ref_value = controller.compute_ref_value(
                    joint_pos,
                    indices=retargeting.optimizer.target_link_human_indices,
                    retargeting_type=str(retargeting.optimizer.retargeting_type),
                )
                maybe_reset_qpos()
                try:
                    import torch

                    with torch.enable_grad():
                        with torch.inference_mode(False):
                            robot_qpos = retargeting.retarget(ref_value)
                except Exception:
                    robot_qpos = retargeting.retarget(ref_value)

                _plot_openxr26_joints(joints_rot, out_path=out_dir / f"{tag}__openxr26_rot.png", title=f"OpenXR26 (rot): {tag}")
                _plot_joint_pos_openpose21(
                    joint_pos,
                    out_path=out_dir / f"{tag}__human_openpose21_preopt.png",
                    title=f"Human pre-opt (rot): {tag}",
                    ref_value=ref_value,
                    human_indices=retargeting.optimizer.target_link_human_indices,
                    retargeting_type=str(retargeting.optimizer.retargeting_type),
                )
                _plot_combined_scene(
                    joint_pos,
                    ref_value=ref_value,
                    human_indices=retargeting.optimizer.target_link_human_indices,
                    retargeting_type=str(retargeting.optimizer.retargeting_type),
                    optimizer=retargeting.optimizer,
                    robot_qpos=robot_qpos,
                    out_path=out_dir / f"{tag}__combined_opt.png",
                    title=f"Human+Robot opt (rot): {tag}",
                )
                opt_loss = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=robot_qpos)
                _plot_loss_summary(
                    out_path=out_dir / f"{tag}__loss.png",
                    title=f"Proxy loss (rot): {tag}",
                    init_loss=None,
                    opt_loss=opt_loss,
                )

    return csv_path


def _try_load_openxr26_seq_from_npz(
    npz_path: Path,
    *,
    seq_key: str = "joints_openxr26",
    seq_track: int = 0,
) -> Optional[Any]:
    """
    Best-effort loader for a sequence NPZ containing OpenXR-26 joints as:
      - (B,T,26,3) under `seq_key`, OR
      - (T,26,3) under `seq_key` (single track already sliced).

    Returns:
      - joints_t263: (T,26,3) float32 if present, else None.
    """
    import numpy as np

    npz_path = Path(npz_path)
    with np.load(npz_path, allow_pickle=True) as npz:
        if seq_key not in npz.files:
            return None
        v = np.asarray(npz[seq_key], dtype=np.float32)
        if v.ndim == 4 and v.shape[-2:] == (26, 3):
            b = int(seq_track)
            if b < 0 or b >= v.shape[0]:
                raise ValueError(f"{npz_path}: --seq-track={b} out of range for {seq_key} with shape {v.shape}")
            return v[b]
        if v.ndim == 3 and v.shape[-2:] == (26, 3):
            return v
        return None


def _grid_search_rotations_seq(
    *,
    controller: "_StandaloneDexTriHandRetargeter",
    hand: str,
    joints_t263,  # (T,26,3)
    tag_base: str,
    out_dir: Path,
    angles_deg: list[float],
    pivot: str,
    step: int = 10,
    max_frames: Optional[int] = None,
    topk_viz: int = 0,
) -> Path:
    """
    Multi-frame rotation grid search on an in-memory OpenXR-26 joint sequence.
    Same output format as `_grid_search_rotations_multi`.
    """
    import csv
    import numpy as np
    from scipy.spatial.transform import Rotation as R

    out_dir.mkdir(parents=True, exist_ok=True)
    hand = str(hand).lower().strip()
    if hand not in ("left", "right"):
        raise ValueError("--grid-hand must be 'left' or 'right'")
    step = max(int(step), 1)

    joints_t263 = np.asarray(joints_t263, dtype=np.float32)
    if joints_t263.ndim != 3 or joints_t263.shape[1:] != (26, 3):
        raise ValueError(f"Expected joints_t263 shape (T,26,3), got {joints_t263.shape}")

    # sample frames by index
    t_idxs = list(range(0, joints_t263.shape[0], step))
    if max_frames is not None:
        t_idxs = t_idxs[: max(int(max_frames), 0)]
    if not t_idxs:
        raise ValueError("No frames selected for sequence multi-frame grid search")

    # Choose retargeting objects
    retargeting = controller._dex_left_hand if hand == "left" else controller._dex_right_hand  # noqa: SLF001
    operator2mano = _OPERATOR2MANO_LEFT if hand == "left" else _OPERATOR2MANO_RIGHT

    # Cache initial qpos for fair resets (if supported).
    init_qpos0 = None
    try:
        if hasattr(retargeting, "get_qpos"):
            init_qpos0 = np.asarray(retargeting.get_qpos(), dtype=np.float32).reshape(-1)
    except Exception:
        init_qpos0 = None

    def maybe_reset_qpos():
        if init_qpos0 is None:
            return
        if hasattr(retargeting, "set_qpos"):
            try:
                retargeting.set_qpos(init_qpos0)
            except Exception:
                pass

    # Precompute rotation matrices for all combos.
    combos: list[tuple[float, float, float, np.ndarray]] = []
    for ax in angles_deg:
        for ay in angles_deg:
            for az in angles_deg:
                mat = R.from_euler("xyz", [ax, ay, az], degrees=True).as_matrix().astype(np.float32)
                combos.append((float(ax), float(ay), float(az), mat))

    # Evaluate: for each combo, accumulate losses across frames.
    summary_rows = []
    for ax, ay, az, rot in combos:
        losses = []
        init_losses = []
        n_used = 0

        for t in t_idxs:
            xyz = joints_t263[int(t)]
            joints = np.asarray(xyz, dtype=np.float32)
            pv = str(pivot).lower().strip()
            if pv == "origin":
                center = np.zeros((1, 3), dtype=np.float32)
            elif pv == "palm":
                center = joints[HAND_JOINT_NAMES.index("palm") : HAND_JOINT_NAMES.index("palm") + 1]
            else:
                center = joints[HAND_JOINT_NAMES.index("wrist") : HAND_JOINT_NAMES.index("wrist") + 1]
            joints_rot = (joints - center) @ rot.T + center

            pose_dict = openxr26_positions_to_pose_dict(joints_rot)
            joint_pos = controller.convert_hand_joints(pose_dict, operator2mano)
            ref_value = controller.compute_ref_value(
                joint_pos,
                indices=retargeting.optimizer.target_link_human_indices,
                retargeting_type=str(retargeting.optimizer.retargeting_type),
            )

            if init_qpos0 is not None:
                init_l = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=init_qpos0)
                if init_l is not None:
                    init_losses.append(float(init_l))

            maybe_reset_qpos()
            try:
                import torch

                with torch.enable_grad():
                    with torch.inference_mode(False):
                        robot_qpos = retargeting.retarget(ref_value)
            except Exception:
                robot_qpos = retargeting.retarget(ref_value)

            opt_l = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=robot_qpos)
            if opt_l is None:
                continue
            losses.append(float(opt_l))
            n_used += 1

        if n_used == 0:
            continue
        arr = np.asarray(losses, dtype=np.float32)
        init_arr = np.asarray(init_losses, dtype=np.float32) if init_losses else None
        summary_rows.append(
            {
                "x_deg": ax,
                "y_deg": ay,
                "z_deg": az,
                "n_frames": int(n_used),
                "mean_opt_loss": float(np.mean(arr)),
                "median_opt_loss": float(np.median(arr)),
                "std_opt_loss": float(np.std(arr)),
                "mean_init_loss": float(np.mean(init_arr)) if init_arr is not None else "",
            }
        )

    summary_rows = sorted(summary_rows, key=lambda r: float(r["mean_opt_loss"]))
    csv_path = out_dir / f"{tag_base}__{hand}__rot_grid_search_multiframe.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "x_deg",
                "y_deg",
                "z_deg",
                "n_frames",
                "mean_opt_loss",
                "median_opt_loss",
                "std_opt_loss",
                "mean_init_loss",
            ],
        )
        w.writeheader()
        w.writerows(summary_rows)

    # Optional: visualize best K rotations on the first sampled frame (representative).
    if topk_viz > 0 and summary_rows:
        t0 = int(t_idxs[0])
        xyz0 = joints_t263[t0]
        best = summary_rows[: max(int(topk_viz), 0)]
        for i, r in enumerate(best):
            ax, ay, az = float(r["x_deg"]), float(r["y_deg"]), float(r["z_deg"])
            tag = f"{tag_base}__{hand}__best{i:02d}__x{ax:+.0f}_y{ay:+.0f}_z{az:+.0f}__t{t0:04d}"
            rot = R.from_euler("xyz", [ax, ay, az], degrees=True).as_matrix().astype(np.float32)
            joints = np.asarray(xyz0, dtype=np.float32)
            pv = str(pivot).lower().strip()
            if pv == "origin":
                center = np.zeros((1, 3), dtype=np.float32)
            elif pv == "palm":
                center = joints[HAND_JOINT_NAMES.index("palm") : HAND_JOINT_NAMES.index("palm") + 1]
            else:
                center = joints[HAND_JOINT_NAMES.index("wrist") : HAND_JOINT_NAMES.index("wrist") + 1]
            joints_rot = (joints - center) @ rot.T + center

            pose_dict = openxr26_positions_to_pose_dict(joints_rot)
            joint_pos = controller.convert_hand_joints(pose_dict, operator2mano)
            ref_value = controller.compute_ref_value(
                joint_pos,
                indices=retargeting.optimizer.target_link_human_indices,
                retargeting_type=str(retargeting.optimizer.retargeting_type),
            )
            maybe_reset_qpos()
            try:
                import torch

                with torch.enable_grad():
                    with torch.inference_mode(False):
                        robot_qpos = retargeting.retarget(ref_value)
            except Exception:
                robot_qpos = retargeting.retarget(ref_value)

            _plot_openxr26_joints(joints_rot, out_path=out_dir / f"{tag}__openxr26_rot.png", title=f"OpenXR26 (rot): {tag}")
            _plot_joint_pos_openpose21(
                joint_pos,
                out_path=out_dir / f"{tag}__human_openpose21_preopt.png",
                title=f"Human pre-opt (rot): {tag}",
                ref_value=ref_value,
                human_indices=retargeting.optimizer.target_link_human_indices,
                retargeting_type=str(retargeting.optimizer.retargeting_type),
            )
            _plot_combined_scene(
                joint_pos,
                ref_value=ref_value,
                human_indices=retargeting.optimizer.target_link_human_indices,
                retargeting_type=str(retargeting.optimizer.retargeting_type),
                optimizer=retargeting.optimizer,
                robot_qpos=robot_qpos,
                out_path=out_dir / f"{tag}__combined_opt.png",
                title=f"Human+Robot opt (rot): {tag}",
            )
            opt_loss = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=robot_qpos)
            _plot_loss_summary(
                out_path=out_dir / f"{tag}__loss.png",
                title=f"Proxy loss (rot): {tag}",
                init_loss=None,
                opt_loss=opt_loss,
            )

    return csv_path


def _describe_npz(npz) -> str:
    """Return a compact description of keys and shapes for error messages."""
    parts = []
    for k in list(getattr(npz, "files", [])):
        try:
            v = npz[k]
            shape = getattr(v, "shape", None)
            dtype = getattr(v, "dtype", None)
            parts.append(f"{k}: shape={shape}, dtype={dtype}")
        except Exception:
            parts.append(f"{k}: <unreadable>")
    return "; ".join(parts)


def _infer_hand_xyz_keys(npz) -> Tuple[Optional[str], Optional[str]]:
    """
    Heuristic key inference for left/right OpenXR-26 joint xyz arrays.
    We look for arrays shaped (26,3), preferring keys that contain 'left'/'right'.
    """
    keys = list(npz.files)

    def is_26x3(k: str) -> bool:
        try:
            v = npz[k]
        except Exception:
            return False
        return getattr(v, "shape", None) == (26, 3)

    left_candidates = [k for k in keys if is_26x3(k) and "left" in k.lower()]
    right_candidates = [k for k in keys if is_26x3(k) and "right" in k.lower()]
    if left_candidates and right_candidates:
        return left_candidates[0], right_candidates[0]

    # Try common names
    common_left = [
        "left_joints_xyz",
        "left_openxr26_xyz",
        "openxr26_left_xyz",
        "openxr26_left",
        "joints_left",
        "joints_xyz_left",
    ]
    common_right = [
        "right_joints_xyz",
        "right_openxr26_xyz",
        "openxr26_right_xyz",
        "openxr26_right",
        "joints_right",
        "joints_xyz_right",
    ]
    for lk in common_left:
        if lk in keys and is_26x3(lk):
            for rk in common_right:
                if rk in keys and getattr(npz[rk], "shape", None) == (26, 3):
                    return lk, rk

    # Fallback: first two (26,3) arrays
    any_26x3 = [k for k in keys if is_26x3(k)]
    if len(any_26x3) >= 2:
        return any_26x3[0], any_26x3[1]
    if len(any_26x3) == 1:
        return any_26x3[0], None
    return None, None


def openxr26_positions_to_pose_dict(joints_xyz, *, wrist_quat_wxyz=None):
    """
    Convert OpenXR-26 joint positions (26,3) to an OpenXR-style pose dict:
      joint_name -> [x, y, z, qw, qx, qy, qz]
    """
    import numpy as np

    joints_xyz = np.asarray(joints_xyz, dtype=np.float32)
    if joints_xyz.shape != (26, 3):
        raise ValueError(f"Expected joints_xyz shape (26,3), got {joints_xyz.shape}")

    if wrist_quat_wxyz is None:
        wrist_quat_wxyz = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    else:
        wrist_quat_wxyz = np.asarray(wrist_quat_wxyz, dtype=np.float32).reshape(-1)
        if wrist_quat_wxyz.shape != (4,):
            raise ValueError(f"Expected wrist_quat_wxyz shape (4,), got {wrist_quat_wxyz.shape}")

    out = {}
    for i, name in enumerate(HAND_JOINT_NAMES):
        p = joints_xyz[i]
        out[name] = np.array([p[0], p[1], p[2], *wrist_quat_wxyz], dtype=np.float32)
    return out


def _quat_mul_wxyz(q1, q2):
    """Quaternion multiply (wxyz): q = q1 ⊗ q2."""
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


def _retarget_abs_wrist_pose_usd_control(wrist_pose_wxyz, *, is_left: bool):
    """
    Same wrist conversion as IsaacLab `G1TriHandUpperBodyRetargeter._retarget_abs`,
    but without `isaaclab.utils.math`.

    In IsaacLab this is effectively: openxr_pose @ transform_pose, where transform_pose is
    a pure rotation (combined_quat). Therefore:
      pos_out = pos_in
      quat_out = quat_in ⊗ combined_quat
    """
    import numpy as np

    wrist_pose_wxyz = np.asarray(wrist_pose_wxyz, dtype=np.float32).reshape(-1)
    if wrist_pose_wxyz.shape != (7,):
        raise ValueError(f"Expected wrist pose shape (7,), got {wrist_pose_wxyz.shape}")
    pos = wrist_pose_wxyz[:3]
    quat = wrist_pose_wxyz[3:]
    combined = _LEFT_WRIST_COMBINED_QUAT_WXYZ if is_left else _RIGHT_WRIST_COMBINED_QUAT_WXYZ
    quat_out = _quat_mul_wxyz(quat, combined)
    return np.concatenate([pos, quat_out]).astype(np.float32)


class _StandaloneDexTriHandRetargeter:
    """Standalone version of IsaacLab's `G1TriHandDexRetargeting` (no `isaaclab` imports)."""

    def __init__(
        self,
        *,
        left_config_yml: Path,
        right_config_yml: Path,
        left_hand_urdf: Path,
        right_hand_urdf: Path,
        viz_dir: Optional[Path] = None,
        viz_tag_prefix: str = "",
    ) -> None:
        import yaml
        from dex_retargeting.retargeting_config import RetargetingConfig

        self._dex_left_hand = self._load_config(
            RetargetingConfig, yaml, cfg_path=left_config_yml, urdf_path=left_hand_urdf
        )
        self._dex_right_hand = self._load_config(
            RetargetingConfig, yaml, cfg_path=right_config_yml, urdf_path=right_hand_urdf
        )

        self.left_dof_names = list(self._dex_left_hand.optimizer.robot.dof_joint_names)
        self.right_dof_names = list(self._dex_right_hand.optimizer.robot.dof_joint_names)
        self.dof_names = self.left_dof_names + self.right_dof_names
        self._viz_dir = Path(viz_dir) if viz_dir is not None else None
        self._viz_tag_prefix = str(viz_tag_prefix)

    @staticmethod
    def _load_config(RetargetingConfig, yaml, *, cfg_path: Path, urdf_path: Path):
        cfg_path = Path(cfg_path)
        urdf_path = Path(urdf_path)
        if not cfg_path.exists():
            raise FileNotFoundError(f"Missing dex-retargeting config: {cfg_path}")
        if not urdf_path.exists():
            raise FileNotFoundError(f"Missing URDF: {urdf_path}")

        with open(cfg_path, "r") as f:
            cfg = yaml.safe_load(f)
        if "retargeting" not in cfg:
            raise ValueError(f"Config file has no 'retargeting' section: {cfg_path}")
        cfg["retargeting"]["urdf_path"] = str(urdf_path)

        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as tf:
            yaml.safe_dump(cfg, tf)
            tmp_path = tf.name
        try:
            return RetargetingConfig.load_from_file(tmp_path).build()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    @staticmethod
    def convert_hand_joints(hand_poses, operator2mano):
        import numpy as np
        from scipy.spatial.transform import Rotation as R

        joint_position = np.zeros((21, 3), dtype=np.float32)
        hand_joints = list(hand_poses.values())
        for i, joint_index in enumerate(_HAND_JOINTS_INDEX):
            joint_position[i] = np.asarray(hand_joints[joint_index][:3], dtype=np.float32)

        joint_position = joint_position - joint_position[0:1, :]
        xr_wrist_quat = np.asarray(hand_poses.get("wrist")[3:], dtype=np.float32)
        wrist_rot = R.from_quat([xr_wrist_quat[1], xr_wrist_quat[2], xr_wrist_quat[3], xr_wrist_quat[0]]).as_matrix()
        return joint_position @ wrist_rot @ np.asarray(operator2mano, dtype=np.float32)

    @staticmethod
    def compute_ref_value(joint_position, indices, retargeting_type: str):
        import numpy as np

        if retargeting_type == "POSITION":
            return joint_position[indices, :]
        origin_indices = indices[0, :]
        task_indices = indices[1, :]
        return joint_position[task_indices, :] - joint_position[origin_indices, :]

    def compute_one_hand(
        self,
        *,
        hand_joints,
        retargeting,
        operator2mano,
        tag: str,
        openxr26_xyz=None,
        do_viz: bool = True,
    ):
        import torch

        joint_pos = self.convert_hand_joints(hand_joints, operator2mano)
        ref_value = self.compute_ref_value(
            joint_pos,
            indices=retargeting.optimizer.target_link_human_indices,
            retargeting_type=retargeting.optimizer.retargeting_type,
        )

        # --- Debug visualization (before optimize) ---
        if self._viz_dir is not None and do_viz:
            viz_tag = f"{self._viz_tag_prefix}{tag}".strip("_")
            try:
                # raw openxr26
                if openxr26_xyz is not None:
                    _plot_openxr26_joints(
                        openxr26_xyz,
                        out_path=self._viz_dir / f"{viz_tag}__openxr26.png",
                        title=f"OpenXR26 joints: {viz_tag}",
                    )
                # openpose21 canonical (+ ref_value overlay)
                _plot_joint_pos_openpose21(
                    joint_pos,
                    out_path=self._viz_dir / f"{viz_tag}__human_openpose21_preopt.png",
                    title=f"Human (OpenPose21 canonical) pre-opt: {viz_tag}",
                    ref_value=ref_value,
                    human_indices=retargeting.optimizer.target_link_human_indices,
                    retargeting_type=str(retargeting.optimizer.retargeting_type),
                )
            except Exception as e:
                # Keep retargeting robust even if plotting fails.
                _append_text(self._viz_dir / "_viz_errors.txt", f"{viz_tag} preopt plot failed: {e}")

        # Try to capture init qpos for before/after robot visualization + proxy loss.
        init_qpos = None
        try:
            if hasattr(retargeting, "get_qpos"):
                init_qpos = retargeting.get_qpos()
        except Exception:
            init_qpos = None

        # Optional combined plot at init qpos
        if self._viz_dir is not None and do_viz and init_qpos is not None:
            viz_tag = f"{self._viz_tag_prefix}{tag}".strip("_")
            try:
                _plot_combined_scene(
                    joint_pos,
                    ref_value=ref_value,
                    human_indices=retargeting.optimizer.target_link_human_indices,
                    retargeting_type=str(retargeting.optimizer.retargeting_type),
                    optimizer=retargeting.optimizer,
                    robot_qpos=init_qpos,
                    out_path=self._viz_dir / f"{viz_tag}__combined_init.png",
                    title=f"Human + Robot (init): {viz_tag}",
                )
            except Exception as e:
                _append_text(self._viz_dir / "_viz_errors.txt", f"{viz_tag} combined(init) plot failed: {e}")

        with torch.enable_grad():
            with torch.inference_mode(False):
                robot_qpos = retargeting.retarget(ref_value)

        # --- Debug visualization (after optimize) ---
        if self._viz_dir is not None and do_viz:
            viz_tag = f"{self._viz_tag_prefix}{tag}".strip("_")
            try:
                _plot_combined_scene(
                    joint_pos,
                    ref_value=ref_value,
                    human_indices=retargeting.optimizer.target_link_human_indices,
                    retargeting_type=str(retargeting.optimizer.retargeting_type),
                    optimizer=retargeting.optimizer,
                    robot_qpos=robot_qpos,
                    out_path=self._viz_dir / f"{viz_tag}__combined_opt.png",
                    title=f"Human + Robot (opt): {viz_tag}",
                )
                _plot_robot_links(
                    robot_qpos,
                    optimizer=retargeting.optimizer,
                    out_path=self._viz_dir / f"{viz_tag}__robot_links_opt.png",
                    title=f"Robot links (opt): {viz_tag}",
                )

                init_loss = None
                if init_qpos is not None:
                    init_loss = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=init_qpos)
                opt_loss = _proxy_loss_from_optimizer(retargeting.optimizer, ref_value=ref_value, robot_qpos=robot_qpos)
                _plot_loss_summary(
                    out_path=self._viz_dir / f"{viz_tag}__loss.png",
                    title=f"Proxy loss (init vs opt): {viz_tag}",
                    init_loss=init_loss,
                    opt_loss=opt_loss,
                )
                # Also write a small text file for easy grepping.
                (self._viz_dir / f"{viz_tag}__loss.txt").write_text(
                    f"init_loss={init_loss}\nopt_loss={opt_loss}\n",
                    encoding="utf-8",
                )
            except Exception as e:
                _append_text(self._viz_dir / "_viz_errors.txt", f"{viz_tag} postopt plot failed: {e}")

        return robot_qpos

    def compute_left(self, left_hand_poses, *, tag: str = "left", openxr26_xyz=None, do_viz: bool = True):
        import numpy as np

        if left_hand_poses is None:
            return np.zeros(len(self.left_dof_names), dtype=np.float32)
        return self.compute_one_hand(
            hand_joints=left_hand_poses,
            retargeting=self._dex_left_hand,
            operator2mano=_OPERATOR2MANO_LEFT,
            tag=tag,
            openxr26_xyz=openxr26_xyz,
            do_viz=do_viz,
        )

    def compute_right(self, right_hand_poses, *, tag: str = "right", openxr26_xyz=None, do_viz: bool = True):
        import numpy as np

        if right_hand_poses is None:
            return np.zeros(len(self.right_dof_names), dtype=np.float32)
        return self.compute_one_hand(
            hand_joints=right_hand_poses,
            retargeting=self._dex_right_hand,
            operator2mano=_OPERATOR2MANO_RIGHT,
            tag=tag,
            openxr26_xyz=openxr26_xyz,
            do_viz=do_viz,
        )

def _load_openxr26_from_npz(
    npz_path: Path,
    *,
    left_key: Optional[str],
    right_key: Optional[str],
    lr_key_2x26x3: Optional[str],
    single_hand: Optional[str] = None,  # "left" | "right" | None
) -> Tuple[Optional[Any], Optional[Any], Optional[str], Optional[str], Optional[str]]:
    """
    Returns (left_xyz, right_xyz, used_left_key, used_right_key, used_lr_key) where:
      - left_xyz/right_xyz are shaped (26,3) float32 or None if missing.
    """
    import numpy as np

    with np.load(npz_path, allow_pickle=True) as npz:
        if lr_key_2x26x3 is not None:
            if lr_key_2x26x3 not in npz.files:
                raise KeyError(
                    f"{npz_path}: missing key '{lr_key_2x26x3}'. Available: {_describe_npz(npz)}"
                )
            v = np.asarray(npz[lr_key_2x26x3], dtype=np.float32)
            if v.shape != (2, 26, 3):
                raise ValueError(f"{npz_path}: expected {lr_key_2x26x3} shape (2,26,3), got {v.shape}")
            return v[0], v[1], None, None, lr_key_2x26x3

        if left_key is None and right_key is None:
            left_key, right_key = _infer_hand_xyz_keys(npz)
            if left_key is None and right_key is None:
                raise ValueError(
                    f"{npz_path}: could not infer any (26,3) OpenXR-26 xyz arrays. "
                    f"Pass --left-key/--right-key or --lr-key-2x26x3. Available: {_describe_npz(npz)}"
                )

            # If only ONE (26,3) array exists, `_infer_hand_xyz_keys` will return it as "left" by default.
            # Allow user to force-mount it as "right" (or "left") when processing single-hand tracks.
            if single_hand is not None:
                sh = str(single_hand).lower().strip()
                if sh not in ("left", "right"):
                    raise ValueError(f"{npz_path}: invalid single_hand='{single_hand}' (expected 'left' or 'right')")
                if left_key is not None and right_key is None and sh == "right":
                    right_key, left_key = left_key, None
                elif right_key is not None and left_key is None and sh == "left":
                    left_key, right_key = right_key, None

        left_xyz = None
        right_xyz = None
        if left_key is not None:
            if left_key not in npz.files:
                raise KeyError(f"{npz_path}: missing key '{left_key}'. Available: {_describe_npz(npz)}")
            left_xyz = np.asarray(npz[left_key], dtype=np.float32)
            if left_xyz.shape != (26, 3):
                raise ValueError(
                    f"{npz_path}: expected {left_key} shape (26,3), got {left_xyz.shape}. "
                    f"Available: {_describe_npz(npz)}"
                )
        if right_key is not None:
            if right_key not in npz.files:
                raise KeyError(f"{npz_path}: missing key '{right_key}'. Available: {_describe_npz(npz)}")
            right_xyz = np.asarray(npz[right_key], dtype=np.float32)
            if right_xyz.shape != (26, 3):
                raise ValueError(
                    f"{npz_path}: expected {right_key} shape (26,3), got {right_xyz.shape}. "
                    f"Available: {_describe_npz(npz)}"
                )
        return left_xyz, right_xyz, left_key, right_key, None


def _load_wrist_pose_from_npz(
    npz_path: Path,
    *,
    left_wrist_pose_key: Optional[str],
    right_wrist_pose_key: Optional[str],
) -> Tuple[Optional[Any], Optional[Any], Optional[str], Optional[str]]:
    """
    Optional helper: load per-hand wrist poses (x,y,z,qw,qx,qy,qz) from an input frame NPZ.
    Returns (left_wrist_pose, right_wrist_pose, used_left_key, used_right_key).
    """
    import numpy as np

    with np.load(npz_path, allow_pickle=True) as npz:
        keys = list(npz.files)

        def _pick_pose(k: Optional[str], candidates: list[str]) -> Tuple[Optional[str], Optional[np.ndarray]]:
            if k is not None:
                if k not in keys:
                    raise KeyError(f"{npz_path}: missing key '{k}'. Available: {_describe_npz(npz)}")
                v = np.asarray(npz[k], dtype=np.float32).reshape(-1)
                if v.shape != (7,):
                    raise ValueError(f"{npz_path}: expected '{k}' shape (7,), got {v.shape}")
                return k, v
            for ck in candidates:
                if ck in keys:
                    v = np.asarray(npz[ck], dtype=np.float32).reshape(-1)
                    if v.shape == (7,):
                        return ck, v
            return None, None

        used_lk, left_pose = _pick_pose(
            left_wrist_pose_key,
            candidates=["left_wrist_pose_wxyz", "left_wrist_pose", "left_wrist_wxyz", "left_wrist"],
        )
        used_rk, right_pose = _pick_pose(
            right_wrist_pose_key,
            candidates=["right_wrist_pose_wxyz", "right_wrist_pose", "right_wrist_wxyz", "right_wrist"],
        )
        return left_pose, right_pose, used_lk, used_rk


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help=(
            "Input .npz file or a directory containing per-frame .npz files. "
            "Also supports a single 'sequence NPZ' containing OpenXR-26 joints as (B,T,26,3) under --seq-key."
        ),
    )
    parser.add_argument(
        "--glob",
        type=str,
        default="*.npz",
        help="When --input is a directory, glob pattern to find frames (default: *.npz).",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output directory to write retargeted command .npz files.",
    )
    parser.add_argument("--sim-device", type=str, default="cpu", help="Torch device for outputs (default: cpu).")
    parser.add_argument(
        "--left-key",
        type=str,
        default=None,
        help="NPZ key for left hand OpenXR-26 xyz array with shape (26,3). If omitted, inferred.",
    )
    parser.add_argument(
        "--right-key",
        type=str,
        default=None,
        help="NPZ key for right hand OpenXR-26 xyz array with shape (26,3). If omitted, inferred.",
    )
    parser.add_argument(
        "--lr-key-2x26x3",
        type=str,
        default=None,
        help="NPZ key for stacked hands xyz with shape (2,26,3) where [0]=left, [1]=right.",
    )
    parser.add_argument(
        "--left-wrist-pose-key",
        type=str,
        default=None,
        help="Optional NPZ key for left wrist pose (7,) as [x,y,z,qw,qx,qy,qz]. If omitted, inferred.",
    )
    parser.add_argument(
        "--right-wrist-pose-key",
        type=str,
        default=None,
        help="Optional NPZ key for right wrist pose (7,) as [x,y,z,qw,qx,qy,qz]. If omitted, inferred.",
    )
    parser.add_argument(
        "--single-hand",
        type=str,
        default=None,
        choices=["left", "right"],
        help=(
            "If the NPZ contains only ONE (26,3) hand array, force it to be treated as this hand. "
            "Useful for single-hand tracks (e.g. track01 is right-hand only)."
        ),
    )
    parser.add_argument(
        "--left-hand-urdf",
        type=str,
        default=None,
        help="Local URDF path for the G1 LEFT hand (required for standalone retargeting).",
    )
    parser.add_argument(
        "--right-hand-urdf",
        type=str,
        default=None,
        help="Local URDF path for the G1 RIGHT hand (required for standalone retargeting).",
    )
    parser.add_argument(
        "--dex-config-dir",
        type=str,
        default=None,
        help=(
            "Directory containing dex-retargeting YAML configs. "
            "If omitted, will try to auto-locate configs (prefers this repo's `examples/mano_hand_retargeter/_DATA`)."
        ),
    )
    parser.add_argument(
        "--left-config",
        type=str,
        default="g1_hand_left_dexpilot.yml",
        help="Left dex-retargeting config filename (within --dex-config-dir).",
    )
    parser.add_argument(
        "--right-config",
        type=str,
        default="g1_hand_right_dexpilot.yml",
        help="Right dex-retargeting config filename (within --dex-config-dir).",
    )
    parser.add_argument(
        "--viz-dir",
        type=str,
        default=None,
        help=(
            "If set, dumps debug PNGs (human joints, ref_value, robot links init/opt, proxy loss) to this directory."
        ),
    )
    parser.add_argument(
        "--viz-every",
        type=int,
        default=1,
        help="Only visualize every N-th frame when processing a directory (default: 1).",
    )
    parser.add_argument(
        "--viz-hands",
        type=str,
        default="both",
        choices=["left", "right", "both"],
        help="Which hands to visualize (default: both).",
    )
    parser.add_argument(
        "--apply-rot",
        type=str,
        default=None,
        help="Optional fixed input rotation as 'x_deg,y_deg,z_deg' applied to OpenXR26 joints before retargeting.",
    )
    parser.add_argument(
        "--apply-rot-left",
        type=str,
        default=None,
        help=(
            "Optional fixed input rotation as 'x_deg,y_deg,z_deg' applied ONLY to the LEFT hand OpenXR26 joints "
            "before retargeting. Overrides --apply-rot/--apply-rot-hand for the left hand."
        ),
    )
    parser.add_argument(
        "--apply-rot-right",
        type=str,
        default=None,
        help=(
            "Optional fixed input rotation as 'x_deg,y_deg,z_deg' applied ONLY to the RIGHT hand OpenXR26 joints "
            "before retargeting. Overrides --apply-rot/--apply-rot-hand for the right hand."
        ),
    )
    parser.add_argument(
        "--apply-rot-hand",
        type=str,
        default="both",
        choices=["left", "right", "both"],
        help="Which hand(s) to apply --apply-rot to (default: both).",
    )
    parser.add_argument(
        "--apply-rot-pivot",
        type=str,
        default="wrist",
        choices=["wrist", "palm", "origin"],
        help="Pivot point for --apply-rot (default: wrist).",
    )
    parser.add_argument(
        "--save-traj-npz",
        type=str,
        default=None,
        help=(
            "If set, also writes a single trajectory NPZ with stacked joint targets for replay in Isaac Sim. "
            "Contains right/left hand joint targets (7 DOF each) when available, plus frame file list."
        ),
    )
    parser.add_argument(
        "--traj-step",
        type=int,
        default=1,
        help="When --save-traj-npz is set, only keep every N-th frame in the saved trajectory (default: 1).",
    )
    parser.add_argument(
        "--traj-frame-dt",
        type=float,
        default=1.0 / 30.0,
        help="Frame timestep (seconds) stored in the trajectory NPZ for replay (default: 1/30).",
    )
    parser.add_argument(
        "--grid-search-rot",
        action="store_true",
        help=(
            "Grid search input XYZ Euler rotations and compare proxy loss. "
            "Supports either (1) a directory of per-frame .npz files, or (2) a single sequence .npz containing "
            "`joints_openxr26` with shape (B,T,26,3) (use --seq-track to choose B)."
        ),
    )
    parser.add_argument(
        "--grid-hand",
        type=str,
        default="right",
        choices=["left", "right"],
        help=(
            "Which hand to run the rotation grid search on (default: right). "
            "DEPRECATED: prefer --grid-hands."
        ),
    )
    parser.add_argument(
        "--grid-hands",
        type=str,
        default=None,
        choices=["left", "right", "both"],
        help="Which hand(s) to run the rotation grid search on. If set, overrides --grid-hand.",
    )
    parser.add_argument(
        "--grid-angles",
        type=str,
        default="-180,-135,-90,-45,0,45,90,135,180",
        help="Comma-separated list of angles (degrees) to sweep for x,y,z (default is your 9-angle set).",
    )
    parser.add_argument(
        "--grid-pivot",
        type=str,
        default="wrist",
        choices=["wrist", "palm", "origin"],
        help="Pivot point for rotating the OpenXR26 joints (default: wrist).",
    )
    parser.add_argument(
        "--grid-out-dir",
        type=str,
        default=None,
        help=(
            "Output directory for grid-search CSV (and optional best-k viz). "
            "Defaults to <output>/rot_grid_search."
        ),
    )
    parser.add_argument(
        "--grid-topk-viz",
        type=int,
        default=0,
        help="If >0, also dump debug PNGs for the best K rotations (default: 0).",
    )
    parser.add_argument(
        "--grid-step",
        type=int,
        default=10,
        help="When running grid search on a directory, only evaluate every N-th frame (default: 10).",
    )
    parser.add_argument(
        "--grid-max-frames",
        type=int,
        default=None,
        help="Optional cap on number of sampled frames for grid search (after applying --grid-step).",
    )
    parser.add_argument(
        "--seq-key",
        type=str,
        default="joints_openxr26",
        help="When --input is a sequence NPZ, the key for OpenXR-26 joint positions (default: joints_openxr26).",
    )
    parser.add_argument(
        "--seq-track",
        type=int,
        default=0,
        help="When --input is a sequence NPZ with shape (B,T,26,3), which track index (B) to use (default: 0).",
    )
    args = parser.parse_args()

    try:
        import numpy as np
        import torch  # noqa: F401
    except Exception as e:
        raise ImportError(
            "Missing required Python deps. Install at least: numpy, torch, scipy, pyyaml, dex_retargeting. "
            "Example: python3 -m pip install numpy torch scipy pyyaml dex-retargeting"
        ) from e

    if args.left_hand_urdf is None or args.right_hand_urdf is None:
        raise ValueError("--left-hand-urdf and --right-hand-urdf are required in standalone mode.")

    # Resolve dex-retargeting config directory.
    dex_dir = Path(args.dex_config_dir) if args.dex_config_dir is not None else None
    if dex_dir is None:
        # Prefer local, repo-relative data first (works out-of-the-box for this repo).
        this_dir = Path(__file__).resolve().parent
        # Fall back to common IsaacLab checkout layouts (best-effort).
        isaaclab_root = os.environ.get("ISAACLAB_PATH", None)
        candidates = [
            this_dir / "_DATA",
            this_dir / "_DATA" / "dex-retargeting",
            # If user provides ISAACLAB_PATH, try to resolve from there.
            (Path(isaaclab_root) / "source/isaaclab/isaaclab/devices/openxr/retargeters/humanoid/unitree/trihand/data/configs/dex-retargeting")
            if isaaclab_root
            else None,
            Path.home()
            / "Documents"
            / "IsaacLab"
            / "source"
            / "isaaclab"
            / "isaaclab"
            / "devices"
            / "openxr"
            / "retargeters"
            / "humanoid"
            / "unitree"
            / "trihand"
            / "data"
            / "configs"
            / "dex-retargeting",
        ]
        dex_dir = next((c for c in candidates if c is not None and c.exists()), None)
    if dex_dir is None or not dex_dir.exists():
        raise FileNotFoundError(
            "Could not locate dex-retargeting YAML configs. "
            "Pass --dex-config-dir pointing to a directory that contains the YAMLs "
            f"(e.g. '{args.left_config}' / '{args.right_config}'). "
            "This repo typically keeps them under `examples/mano_hand_retargeter/_DATA`."
        )

    left_cfg = dex_dir / args.left_config
    right_cfg = dex_dir / args.right_config

    controller = _StandaloneDexTriHandRetargeter(
        left_config_yml=left_cfg,
        right_config_yml=right_cfg,
        left_hand_urdf=Path(args.left_hand_urdf),
        right_hand_urdf=Path(args.right_hand_urdf),
        viz_dir=Path(args.viz_dir) if args.viz_dir else None,
        viz_tag_prefix="",
    )
    hand_joint_names = list(controller.dof_names)

    in_path = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    viz_dir = Path(args.viz_dir) if args.viz_dir else None
    if viz_dir is not None:
        viz_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------
    # Rotation grid search mode (single file only)
    # ------------------------------------------------------------
    if args.grid_search_rot:
        angles = _parse_float_list(args.grid_angles)
        if not angles:
            raise ValueError("--grid-angles parsed to an empty list")

        grid_hands = args.grid_hands if args.grid_hands is not None else args.grid_hand
        grid_out_dir = Path(args.grid_out_dir) if args.grid_out_dir else (out_dir / "rot_grid_search")

        grid_out_dir = Path(args.grid_out_dir) if args.grid_out_dir else (out_dir / "rot_grid_search")

        if in_path.is_dir():
            # Multi-frame mode: evaluate directory with stride
            frame_paths = sorted(in_path.glob(args.glob))
            if not frame_paths:
                raise FileNotFoundError(f"No input frames found under {in_path} with glob '{args.glob}'")
            hands_to_run = ["left", "right"] if grid_hands == "both" else [grid_hands]
            csv_paths = []
            for h in hands_to_run:
                csv_path = _grid_search_rotations_multi(
                    controller=controller,
                    hand=str(h),
                    frame_paths=frame_paths,
                    tag_base=in_path.name,
                    out_dir=grid_out_dir,
                    angles_deg=angles,
                    pivot=args.grid_pivot,
                    step=int(args.grid_step),
                    max_frames=args.grid_max_frames,
                    topk_viz=int(args.grid_topk_viz),
                    left_key=args.left_key,
                    right_key=args.right_key,
                    lr_key_2x26x3=args.lr_key_2x26x3,
                    single_hand=args.single_hand,
                )
                csv_paths.append(csv_path)
                print(f"[grid-search] wrote (multi-frame) {h}: {csv_path}")
            if len(csv_paths) == 1:
                print(f"[grid-search] wrote (multi-frame): {csv_paths[0]}")
            return

        # Single file mode: either a sequence NPZ (multi-frame) or a single-frame NPZ.
        seq = _try_load_openxr26_seq_from_npz(in_path, seq_key=str(args.seq_key), seq_track=int(args.seq_track))
        if seq is not None:
            if grid_hands == "both":
                raise ValueError(
                    "Sequence NPZ grid search assumes the file contains ONE hand's joints. "
                    "Run twice (left/right) with the corresponding input file."
                )
            csv_path = _grid_search_rotations_seq(
                controller=controller,
                hand=str(grid_hands),
                joints_t263=seq,
                tag_base=in_path.stem,
                out_dir=grid_out_dir,
                angles_deg=angles,
                pivot=args.grid_pivot,
                step=int(args.grid_step),
                max_frames=args.grid_max_frames,
                topk_viz=int(args.grid_topk_viz),
            )
            print(f"[grid-search] wrote (sequence) {grid_hands}: {csv_path}")
            return

        # Single-frame NPZ: evaluate one file
        left_xyz, right_xyz, used_left_key, used_right_key, used_lr_key_2x26x3 = _load_openxr26_from_npz(
            in_path,
            left_key=args.left_key,
            right_key=args.right_key,
            lr_key_2x26x3=args.lr_key_2x26x3,
            single_hand=args.single_hand,
        )
        hands_to_run = ["left", "right"] if grid_hands == "both" else [grid_hands]
        for h in hands_to_run:
            openxr26_xyz = left_xyz if str(h) == "left" else right_xyz
            if openxr26_xyz is None:
                raise ValueError(
                    f"Grid search requested for {h} but that hand has no (26,3) array. "
                    f"Try --single-hand {h} or pass explicit keys."
                )

            csv_path = _grid_search_rotations(
                controller=controller,
                hand=str(h),
                openxr26_xyz=openxr26_xyz,
                tag_base=in_path.stem,
                out_dir=grid_out_dir,
                angles_deg=angles,
                pivot=args.grid_pivot,
                topk_viz=int(args.grid_topk_viz),
            )
            print(f"[grid-search] wrote {h}: {csv_path}")
        return

    # ------------------------------------------------------------
    # Normal retargeting mode: per-frame NPZs OR a single sequence NPZ
    # ------------------------------------------------------------

    # Sequence NPZ mode (single file containing (B,T,26,3) or (T,26,3))
    if in_path.is_file() and in_path.suffix.lower() == ".npz":
        seq = _try_load_openxr26_seq_from_npz(in_path, seq_key=str(args.seq_key), seq_track=int(args.seq_track))
    else:
        seq = None

    if seq is not None:
        # This sequence format does not encode left+right in a single file; user should pass a left-only
        # or right-only sequence, and specify which hand it is with --single-hand.
        if args.single_hand is None:
            raise ValueError(
                "Sequence NPZ input detected (via --seq-key), but --single-hand was not set. "
                "Pass --single-hand left or --single-hand right to indicate which hand this file represents."
            )

        seq_hand = str(args.single_hand).lower().strip()
        if seq_hand not in ("left", "right"):
            raise ValueError("--single-hand must be 'left' or 'right' for sequence NPZ mode.")

        seq = np.asarray(seq, dtype=np.float32)
        if seq.ndim != 3 or seq.shape[1:] != (26, 3):
            raise ValueError(f"Sequence NPZ {in_path}: expected (T,26,3) after slicing, got {seq.shape}")

        T = int(seq.shape[0])
        used_left_key = str(args.seq_key) if seq_hand == "left" else None
        used_right_key = str(args.seq_key) if seq_hand == "right" else None
        used_lr_key_2x26x3 = None
        used_left_wrist_key = None
        used_right_wrist_key = None

        # Rotation parsing (mirrors per-frame mode below).
        def _parse_rot_seq(name: str, s: Optional[str]):
            if s is None:
                return None
            vals = _parse_float_list(s)
            if len(vals) != 3:
                raise ValueError(f"{name} must be 'x_deg,y_deg,z_deg' (3 numbers)")
            return (float(vals[0]), float(vals[1]), float(vals[2]))

        apply_rot_global = _parse_rot_seq("--apply-rot", args.apply_rot)
        apply_rot_left = _parse_rot_seq("--apply-rot-left", args.apply_rot_left)
        apply_rot_right = _parse_rot_seq("--apply-rot-right", args.apply_rot_right)

        # Optional trajectory accumulation for replay.
        traj_paths: list[str] = []
        traj_left_q: list[Any] = []
        traj_right_q: list[Any] = []
        traj_left_wrist: list[Any] = []
        traj_right_wrist: list[Any] = []

        for frame_i in range(T):
            xyz = seq[frame_i]
            left_xyz = xyz if seq_hand == "left" else None
            right_xyz = xyz if seq_hand == "right" else None
            left_wrist_pose = None
            right_wrist_pose = None

            # Apply fixed rotations (if requested) before pose dict conversion.
            if left_xyz is not None:
                rot_l = apply_rot_left
                if rot_l is None and apply_rot_global is not None and args.apply_rot_hand in ("left", "both"):
                    rot_l = apply_rot_global
                if rot_l is not None:
                    left_xyz = _rotate_openxr26_xyz(left_xyz, euler_xyz_deg=rot_l, pivot=args.apply_rot_pivot)

            if right_xyz is not None:
                rot_r = apply_rot_right
                if rot_r is None and apply_rot_global is not None and args.apply_rot_hand in ("right", "both"):
                    rot_r = apply_rot_global
                if rot_r is not None:
                    right_xyz = _rotate_openxr26_xyz(right_xyz, euler_xyz_deg=rot_r, pivot=args.apply_rot_pivot)

            left_pose_dict = None if left_xyz is None else openxr26_positions_to_pose_dict(left_xyz)
            right_pose_dict = None if right_xyz is None else openxr26_positions_to_pose_dict(right_xyz)

            default_pose = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
            left_wrist = (
                default_pose
                if left_pose_dict is None
                else (left_wrist_pose if left_wrist_pose is not None else left_pose_dict.get("wrist", default_pose))
            )
            right_wrist = (
                default_pose
                if right_pose_dict is None
                else (right_wrist_pose if right_wrist_pose is not None else right_pose_dict.get("wrist", default_pose))
            )

            do_viz = args.viz_dir is not None and (frame_i % max(int(args.viz_every), 1) == 0)
            tag_base = f"{in_path.stem}__b{int(args.seq_track):02d}__t{frame_i:04d}"

            do_viz_left = do_viz and args.viz_hands in ("left", "both")
            do_viz_right = do_viz and args.viz_hands in ("right", "both")

            left_q = (
                controller.compute_left(
                    left_pose_dict,
                    tag=f"{tag_base}__left",
                    openxr26_xyz=left_xyz if do_viz_left else None,
                    do_viz=do_viz_left,
                )
                if left_pose_dict is not None
                else np.zeros(len(controller.left_dof_names), dtype=np.float32)
            )
            right_q = (
                controller.compute_right(
                    right_pose_dict,
                    tag=f"{tag_base}__right",
                    openxr26_xyz=right_xyz if do_viz_right else None,
                    do_viz=do_viz_right,
                )
                if right_pose_dict is not None
                else np.zeros(len(controller.right_dof_names), dtype=np.float32)
            )
            hand_joints = np.concatenate([np.asarray(left_q, dtype=np.float32), np.asarray(right_q, dtype=np.float32)])

            left_wrist_cmd = _retarget_abs_wrist_pose_usd_control(left_wrist, is_left=True)
            right_wrist_cmd = _retarget_abs_wrist_pose_usd_control(right_wrist, is_left=False)
            cmd_np = np.concatenate([left_wrist_cmd, right_wrist_cmd, hand_joints]).astype(np.float32)

            out_path = out_dir / f"{in_path.stem}_b{int(args.seq_track):02d}_t{frame_i:04d}_g1_upper_body_cmd.npz"
            np.savez_compressed(
                out_path,
                cmd=cmd_np,
                left_wrist=cmd_np[:7],
                right_wrist=cmd_np[7:14],
                hand_joints=cmd_np[14:],
                hand_joint_names=np.array(hand_joint_names, dtype=object),
                input_file=str(in_path),
                input_frame_index=int(frame_i),
                seq_key=str(args.seq_key),
                seq_track=int(args.seq_track),
                used_left_key=used_left_key,
                used_right_key=used_right_key,
                used_lr_key_2x26x3=used_lr_key_2x26x3,
                used_left_wrist_pose_key=used_left_wrist_key,
                used_right_wrist_pose_key=used_right_wrist_key,
            )

            if args.save_traj_npz is not None and (frame_i % max(int(args.traj_step), 1) == 0):
                traj_paths.append(f"{str(in_path)}::t={frame_i:04d}")
                traj_left_q.append(np.asarray(left_q, dtype=np.float32).reshape(-1))
                traj_right_q.append(np.asarray(right_q, dtype=np.float32).reshape(-1))
                traj_left_wrist.append(np.asarray(left_wrist_cmd, dtype=np.float32).reshape(7))
                traj_right_wrist.append(np.asarray(right_wrist_cmd, dtype=np.float32).reshape(7))

        print(f"Wrote {T} command file(s) to: {out_dir}")

        if args.save_traj_npz is not None:
            traj_path = Path(args.save_traj_npz).expanduser().resolve()
            traj_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                traj_path,
                frame_files=np.array(traj_paths, dtype=object),
                frame_dt=float(args.traj_frame_dt),
                left_wrist=np.stack(traj_left_wrist, axis=0)
                if traj_left_wrist
                else np.zeros((0, 7), dtype=np.float32),
                right_wrist=np.stack(traj_right_wrist, axis=0)
                if traj_right_wrist
                else np.zeros((0, 7), dtype=np.float32),
                left_hand_q=np.stack(traj_left_q, axis=0) if traj_left_q else np.zeros((0, 7), dtype=np.float32),
                right_hand_q=np.stack(traj_right_q, axis=0) if traj_right_q else np.zeros((0, 7), dtype=np.float32),
                left_dof_names=np.array(controller.left_dof_names, dtype=object),
                right_dof_names=np.array(controller.right_dof_names, dtype=object),
                input_file=str(in_path),
                seq_key=str(args.seq_key),
                seq_track=int(args.seq_track),
            )
            print(f"[traj] wrote: {traj_path} (T={len(traj_paths)})")
        return

    # Per-frame NPZ mode (directory or single per-frame NPZ)
    if in_path.is_dir():
        frame_paths = sorted(in_path.glob(args.glob))
    else:
        frame_paths = [in_path]

    if not frame_paths:
        raise FileNotFoundError(f"No input frames found under {in_path} with glob '{args.glob}'")

    def _parse_rot(name: str, s: Optional[str]):
        if s is None:
            return None
        vals = _parse_float_list(s)
        if len(vals) != 3:
            raise ValueError(f"{name} must be 'x_deg,y_deg,z_deg' (3 numbers)")
        return (float(vals[0]), float(vals[1]), float(vals[2]))

    # Backward-compatible rotation handling:
    # - If --apply-rot-left/right are provided, they override global --apply-rot for that hand.
    # - Otherwise, use --apply-rot + --apply-rot-hand.
    apply_rot_global = _parse_rot("--apply-rot", args.apply_rot)
    apply_rot_left = _parse_rot("--apply-rot-left", args.apply_rot_left)
    apply_rot_right = _parse_rot("--apply-rot-right", args.apply_rot_right)

    # Optional trajectory accumulation for replay.
    traj_paths: list[str] = []
    traj_left_q: list[Any] = []
    traj_right_q: list[Any] = []
    traj_left_wrist: list[Any] = []
    traj_right_wrist: list[Any] = []

    for frame_i, p in enumerate(frame_paths):
        left_xyz, right_xyz, used_left_key, used_right_key, used_lr_key_2x26x3 = _load_openxr26_from_npz(
            p,
            left_key=args.left_key,
            right_key=args.right_key,
            lr_key_2x26x3=args.lr_key_2x26x3,
            single_hand=args.single_hand,
        )
        # Optional: load wrist poses (lets replay place the robot in world view).
        left_wrist_pose, right_wrist_pose, used_left_wrist_key, used_right_wrist_key = _load_wrist_pose_from_npz(
            p,
            left_wrist_pose_key=args.left_wrist_pose_key,
            right_wrist_pose_key=args.right_wrist_pose_key,
        )

        # Apply fixed rotations (if requested) before pose dict conversion.
        # Per-hand rotations override global rotation for that hand.
        if left_xyz is not None:
            rot_l = apply_rot_left
            if rot_l is None and apply_rot_global is not None and args.apply_rot_hand in ("left", "both"):
                rot_l = apply_rot_global
            if rot_l is not None:
                left_xyz = _rotate_openxr26_xyz(left_xyz, euler_xyz_deg=rot_l, pivot=args.apply_rot_pivot)

        if right_xyz is not None:
            rot_r = apply_rot_right
            if rot_r is None and apply_rot_global is not None and args.apply_rot_hand in ("right", "both"):
                rot_r = apply_rot_global
            if rot_r is not None:
                right_xyz = _rotate_openxr26_xyz(right_xyz, euler_xyz_deg=rot_r, pivot=args.apply_rot_pivot)

        # Important: we keep wrist orientation identity for retargeting unless you explicitly embed it into xyz->pose.
        # (Most datasets only have positions; orientation often needs a separate alignment step.)
        left_pose_dict = None if left_xyz is None else openxr26_positions_to_pose_dict(left_xyz)
        right_pose_dict = None if right_xyz is None else openxr26_positions_to_pose_dict(right_xyz)

        default_pose = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        # Use provided wrist poses if present, else fall back to pose dict (position from joints, identity orientation).
        left_wrist = (
            default_pose
            if left_pose_dict is None
            else (left_wrist_pose if left_wrist_pose is not None else left_pose_dict.get("wrist", default_pose))
        )
        right_wrist = (
            default_pose
            if right_pose_dict is None
            else (right_wrist_pose if right_wrist_pose is not None else right_pose_dict.get("wrist", default_pose))
        )

        do_viz = args.viz_dir is not None and (frame_i % max(int(args.viz_every), 1) == 0)
        tag_base = p.stem

        # If visualization is requested but the requested hand is missing, warn loudly.
        if do_viz and viz_dir is not None:
            if args.viz_hands in ("right", "both") and right_pose_dict is None:
                msg = (
                    f"[viz] {p.name}: requested right-hand viz but no right-hand (26,3) array was found/inferred. "
                    f"Pass --right-key/--lr-key-2x26x3 if the data exists."
                )
                print(msg)
                _append_text(viz_dir / "_viz_status.txt", msg)
            if args.viz_hands in ("left", "both") and left_pose_dict is None:
                msg = (
                    f"[viz] {p.name}: requested left-hand viz but no left-hand (26,3) array was found/inferred. "
                    f"Pass --left-key/--lr-key-2x26x3 if the data exists."
                )
                print(msg)
                _append_text(viz_dir / "_viz_status.txt", msg)

        do_viz_left = do_viz and args.viz_hands in ("left", "both")
        do_viz_right = do_viz and args.viz_hands in ("right", "both")

        left_q = (
            controller.compute_left(
                left_pose_dict,
                tag=f"{tag_base}__left",
                openxr26_xyz=left_xyz if do_viz_left else None,
                do_viz=do_viz_left,
            )
            if left_pose_dict is not None
            else np.zeros(len(controller.left_dof_names), dtype=np.float32)
        )
        right_q = (
            controller.compute_right(
                right_pose_dict,
                tag=f"{tag_base}__right",
                openxr26_xyz=right_xyz if do_viz_right else None,
                do_viz=do_viz_right,
            )
            if right_pose_dict is not None
            else np.zeros(len(controller.right_dof_names), dtype=np.float32)
        )
        hand_joints = np.concatenate([np.asarray(left_q, dtype=np.float32), np.asarray(right_q, dtype=np.float32)])

        left_wrist_cmd = _retarget_abs_wrist_pose_usd_control(left_wrist, is_left=True)
        right_wrist_cmd = _retarget_abs_wrist_pose_usd_control(right_wrist, is_left=False)
        cmd_np = np.concatenate([left_wrist_cmd, right_wrist_cmd, hand_joints]).astype(np.float32)

        out_path = out_dir / (p.stem + "_g1_upper_body_cmd.npz")
        np.savez_compressed(
            out_path,
            cmd=cmd_np,
            left_wrist=cmd_np[:7],
            right_wrist=cmd_np[7:14],
            hand_joints=cmd_np[14:],
            hand_joint_names=np.array(hand_joint_names, dtype=object),
            input_file=str(p),
            used_left_key=used_left_key,
            used_right_key=used_right_key,
            used_lr_key_2x26x3=used_lr_key_2x26x3,
            used_left_wrist_pose_key=used_left_wrist_key,
            used_right_wrist_pose_key=used_right_wrist_key,
        )

        # Trajectory accumulation (keep every Nth frame).
        if args.save_traj_npz is not None and (frame_i % max(int(args.traj_step), 1) == 0):
            traj_paths.append(str(p))
            traj_left_q.append(np.asarray(left_q, dtype=np.float32).reshape(-1))
            traj_right_q.append(np.asarray(right_q, dtype=np.float32).reshape(-1))
            traj_left_wrist.append(np.asarray(left_wrist_cmd, dtype=np.float32).reshape(7))
            traj_right_wrist.append(np.asarray(right_wrist_cmd, dtype=np.float32).reshape(7))

    print(f"Wrote {len(frame_paths)} command file(s) to: {out_dir}")

    if args.save_traj_npz is not None:
        traj_path = Path(args.save_traj_npz).expanduser().resolve()
        traj_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            traj_path,
            frame_files=np.array(traj_paths, dtype=object),
            frame_dt=float(args.traj_frame_dt),
            # Wrist poses (USD control frame)
            left_wrist=np.stack(traj_left_wrist, axis=0) if traj_left_wrist else np.zeros((0, 7), dtype=np.float32),
            right_wrist=np.stack(traj_right_wrist, axis=0) if traj_right_wrist else np.zeros((0, 7), dtype=np.float32),
            # Joint targets (dex-retargeting order)
            left_hand_q=np.stack(traj_left_q, axis=0) if traj_left_q else np.zeros((0, 7), dtype=np.float32),
            right_hand_q=np.stack(traj_right_q, axis=0) if traj_right_q else np.zeros((0, 7), dtype=np.float32),
            left_dof_names=np.array(controller.left_dof_names, dtype=object),
            right_dof_names=np.array(controller.right_dof_names, dtype=object),
        )
        print(f"[traj] wrote: {traj_path} (T={len(traj_paths)})")


if __name__ == "__main__":
    main()


