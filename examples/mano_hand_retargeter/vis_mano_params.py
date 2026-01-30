#!/usr/bin/env python3
"""
Visualize what's inside MANO pose/shape parameters and what MANO outputs.

Supports two common input modes:
  1) Dyn-HaMR results: point at a phase directory that contains "*_results.npz"
     (e.g. <log_dir>/smooth_fit/). We'll load the latest "world" results.
  2) A standalone .npz/.pkl with MANO parameters (betas, global_orient/root_orient,
     hand_pose/body_pose, transl/trans).

Outputs:
  - A text summary of tensor shapes / basic stats
  - Plots showing pose/shape over time (if T>1)
  - A rendered PNG of the MANO mesh + joints for a chosen frame
  - Optionally exports a GLB scene for interactive inspection
"""

import os
import sys
import argparse
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import torch

# Make imports work whether run from repo root or from inside dyn-hamr/
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

# Offscreen rendering defaults
if "PYOPENGL_PLATFORM" not in os.environ:
    os.environ["PYOPENGL_PLATFORM"] = "egl"

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import trimesh

from omegaconf import OmegaConf

from body_model import MANO
from body_model.utils import run_mano
from util.loaders import resolve_cfg_paths
from optim.output import get_results_paths, load_result
from vis.viewer import init_viewer
from geometry.mesh import save_meshes_to_glb


OPENPOSE_HAND_EDGES = [
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
    (19, 20),  # pinky
]

# OpenXR joint order used by IsaacLab (`isaaclab.devices.openxr.common.HAND_JOINT_NAMES`)
HAND_JOINT_NAMES = [
    # Palm
    "palm",
    # Wrist
    "wrist",
    # Thumb
    "thumb_metacarpal",
    "thumb_proximal",
    "thumb_distal",
    "thumb_tip",
    # Index
    "index_metacarpal",
    "index_proximal",
    "index_intermediate",
    "index_distal",
    "index_tip",
    # Middle
    "middle_metacarpal",
    "middle_proximal",
    "middle_intermediate",
    "middle_distal",
    "middle_tip",
    # Ring
    "ring_metacarpal",
    "ring_proximal",
    "ring_intermediate",
    "ring_distal",
    "ring_tip",
    # Little
    "little_metacarpal",
    "little_proximal",
    "little_intermediate",
    "little_distal",
    "little_tip",
]


def openpose21_to_openxr26_joints(j21: np.ndarray, metacarpal_alpha: float = 0.3) -> np.ndarray:
    """
    Convert OpenPose-21 hand joints to OpenXR-26 joint positions (HAND_JOINT_NAMES order).

    OpenPose order assumed:
      0 wrist
      1-4 thumb (CMC, MCP, IP, TIP)
      5-8 index (MCP, PIP, DIP, TIP)
      9-12 middle
      13-16 ring
      17-20 little
    """
    j21 = np.asarray(j21, dtype=np.float32)
    if j21.shape != (21, 3):
        raise ValueError(f"Expected joints shape (21,3); got {tuple(j21.shape)}")

    wrist = j21[0]
    thumb = j21[1:5]
    index = j21[5:9]
    middle = j21[9:13]
    ring = j21[13:17]
    little = j21[17:21]

    # Approximate palm by mean of MCPs (OpenPose doesn't have palm)
    palm = np.mean(np.stack([index[0], middle[0], ring[0], little[0]], axis=0), axis=0)

    def metacarpal_from_mcp(mcp: np.ndarray) -> np.ndarray:
        return wrist + float(metacarpal_alpha) * (mcp - wrist)

    out = {}
    out["palm"] = palm
    out["wrist"] = wrist

    # Thumb already has a "metacarpal" in OpenPose indexing
    out["thumb_metacarpal"] = thumb[0]
    out["thumb_proximal"] = thumb[1]
    out["thumb_distal"] = thumb[2]
    out["thumb_tip"] = thumb[3]

    # For other fingers, OpenXR has an extra "metacarpal" joint between wrist and MCP
    out["index_metacarpal"] = metacarpal_from_mcp(index[0])
    out["index_proximal"] = index[0]
    out["index_intermediate"] = index[1]
    out["index_distal"] = index[2]
    out["index_tip"] = index[3]

    out["middle_metacarpal"] = metacarpal_from_mcp(middle[0])
    out["middle_proximal"] = middle[0]
    out["middle_intermediate"] = middle[1]
    out["middle_distal"] = middle[2]
    out["middle_tip"] = middle[3]

    out["ring_metacarpal"] = metacarpal_from_mcp(ring[0])
    out["ring_proximal"] = ring[0]
    out["ring_intermediate"] = ring[1]
    out["ring_distal"] = ring[2]
    out["ring_tip"] = ring[3]

    out["little_metacarpal"] = metacarpal_from_mcp(little[0])
    out["little_proximal"] = little[0]
    out["little_intermediate"] = little[1]
    out["little_distal"] = little[2]
    out["little_tip"] = little[3]

    missing = [k for k in HAND_JOINT_NAMES if k not in out]
    if missing:
        raise RuntimeError(f"Internal error: missing OpenXR joints: {missing}")

    return np.stack([out[n] for n in HAND_JOINT_NAMES], axis=0).astype(np.float32)


@dataclass
class ManoParams:
    trans: torch.Tensor  # (B,T,3)
    root_orient: torch.Tensor  # (B,T,3)
    hand_pose: torch.Tensor  # (B,T,45) or (B,T,15,3)
    betas: Optional[torch.Tensor] = None  # (B,D)
    is_right: Optional[torch.Tensor] = None  # (B,T) in {0,1}


def _to_numpy(x: Any) -> np.ndarray:
    if isinstance(x, np.ndarray):
        return x
    if torch.is_tensor(x):
        return x.detach().cpu().numpy()
    return np.asarray(x)


def _as_torch(x: Any, device: torch.device, dtype=torch.float32) -> torch.Tensor:
    if x is None:
        return None
    if torch.is_tensor(x):
        return x.to(device=device, dtype=dtype)
    return torch.as_tensor(x, device=device, dtype=dtype)


def _load_any(path: str) -> Dict[str, Any]:
    if path.endswith(".npz"):
        data = np.load(path, allow_pickle=True)
        # Common Dyn-HaMR convention: a single pickled dict stored under "world" (or similar)
        # in files like "*_world_results.npz".
        def _maybe_unwrap_pickled_dict(key: str) -> Optional[Dict[str, Any]]:
            if key not in data.files:
                return None
            arr = data[key]
            # A pickled python object is typically stored as a 0-d numpy array.
            if getattr(arr, "shape", None) == ():
                try:
                    obj = arr.item()
                except Exception:
                    return None
                if isinstance(obj, dict):
                    # Sometimes we get {"world": {...}} nested one more level.
                    if "world" in obj and isinstance(obj["world"], dict):
                        return obj["world"]
                    return obj
            return None

        for k in ["world", "results", "data", "output"]:
            d = _maybe_unwrap_pickled_dict(k)
            if d is not None:
                return d

        return {k: data[k] for k in data.files}
    if path.endswith(".npy"):
        return {"array": np.load(path, allow_pickle=True)}
    if path.endswith(".pkl") or path.endswith(".pickle"):
        import pickle

        with open(path, "rb") as f:
            obj = pickle.load(f)
        if isinstance(obj, dict):
            return obj
        return {"object": obj}
    raise ValueError(f"Unsupported input file: {path}")


def _pick(d: Dict[str, Any], keys) -> Optional[Any]:
    for k in keys:
        if k in d:
            return d[k]
    return None


def _ensure_bt3(x: torch.Tensor, name: str) -> torch.Tensor:
    # Accept (T,3), (B,T,3), (B,3), (3,)
    if x.ndim == 1 and x.shape[0] == 3:
        x = x[None, None, :]
    elif x.ndim == 2 and x.shape[-1] == 3:
        # assume (T,3) or (B,3)
        if x.shape[0] > 1:
            x = x[None, :, :]
        else:
            x = x[:, None, :]
    elif x.ndim == 3 and x.shape[-1] == 3:
        pass
    else:
        raise ValueError(f"{name} must end with (...,3); got shape {tuple(x.shape)}")
    return x


def _ensure_bt45(x: torch.Tensor, name: str) -> torch.Tensor:
    # Accept (T,45), (B,T,45), (B,45), (45,), (B,T,15,3), (T,15,3)
    if x.ndim == 1 and x.shape[0] == 45:
        x = x[None, None, :]
    elif x.ndim == 2:
        if x.shape[-1] == 45:
            # (T,45) or (B,45)
            if x.shape[0] > 1:
                x = x[None, :, :]
            else:
                x = x[:, None, :]
        elif x.shape == (15, 3):
            x = x.reshape(1, 1, 45)
        else:
            raise ValueError(f"{name} expected (...,45) or (15,3); got {tuple(x.shape)}")
    elif x.ndim == 3:
        if x.shape[-1] == 45:
            x = x  # (B,T,45)
        elif x.shape[-2:] == (15, 3):
            x = x.reshape(x.shape[0], x.shape[1], 45)
        else:
            raise ValueError(f"{name} expected (...,45) or (...,15,3); got {tuple(x.shape)}")
    elif x.ndim == 4 and x.shape[-2:] == (15, 3):
        x = x.reshape(x.shape[0], x.shape[1], 45)
    else:
        raise ValueError(f"{name} expected pose with 15 joints; got {tuple(x.shape)}")
    return x


def load_mano_params_from_dynhamr_phase(phase_dir: str, device: torch.device) -> ManoParams:
    res_paths = get_results_paths(phase_dir)
    if len(res_paths) < 1:
        raise FileNotFoundError(f"No '*_results.npz' found in: {phase_dir}")
    it = sorted(res_paths.keys())[-1]
    res = load_result(res_paths[it])
    if "world" not in res:
        raise KeyError(f"Expected 'world' results at iteration {it}; found keys: {list(res.keys())}")
    d = res["world"]

    # Common Dyn-HaMR naming
    trans = _pick(d, ["trans", "transl"])
    root_orient = _pick(d, ["root_orient", "global_orient"])
    pose = _pick(d, ["pose_body", "hand_pose", "body_pose"])
    betas = _pick(d, ["betas", "shape", "body_shape"])
    is_right = _pick(d, ["is_right", "handedness"])

    if trans is None or root_orient is None or pose is None:
        raise KeyError(
            f"Could not find required MANO params in world results. "
            f"Need trans + root_orient + pose. Found keys: {list(d.keys())}"
        )

    trans = _ensure_bt3(_as_torch(trans, device), "trans")
    root_orient = _ensure_bt3(_as_torch(root_orient, device), "root_orient")
    hand_pose = _ensure_bt45(_as_torch(pose, device), "hand_pose")

    # Ensure betas is (B,D)
    betas_t = None
    if betas is not None:
        betas_t = _as_torch(betas, device)
        if betas_t.ndim == 1:
            betas_t = betas_t[None, :]
        elif betas_t.ndim == 2:
            pass
        elif betas_t.ndim == 3:
            # (B,T,D) -> take first frame (usually constant)
            betas_t = betas_t[:, 0, :]
        else:
            raise ValueError(f"betas/shape must be (D) or (B,D) or (B,T,D); got {tuple(betas_t.shape)}")

    is_right_t = None
    if is_right is not None:
        is_right_t = _as_torch(is_right, device, dtype=torch.float32)
        # Accept (B,T), (T,), (B,)
        if is_right_t.ndim == 1:
            if is_right_t.shape[0] == trans.shape[1]:
                is_right_t = is_right_t[None, :]
            else:
                is_right_t = is_right_t[:, None].expand(trans.shape[0], trans.shape[1])
        elif is_right_t.ndim == 2:
            pass
        else:
            raise ValueError(f"is_right must be (B,T) or (T,) or (B,); got {tuple(is_right_t.shape)}")
        # round to {0,1}
        is_right_t = (is_right_t >= 0.5).float()

    return ManoParams(trans=trans, root_orient=root_orient, hand_pose=hand_pose, betas=betas_t, is_right=is_right_t)


def load_mano_params_from_file(params_path: str, device: torch.device) -> ManoParams:
    d = _load_any(params_path)

    trans = _pick(d, ["trans", "transl", "t", "translation"])
    root_orient = _pick(d, ["root_orient", "global_orient", "global_orient_aa"])
    hand_pose = _pick(d, ["hand_pose", "pose", "pose_body", "body_pose"])
    betas = _pick(d, ["betas", "shape", "body_shape"])
    is_right = _pick(d, ["is_right", "handedness"])

    if trans is None or root_orient is None or hand_pose is None:
        raise KeyError(
            f"params file must contain trans + root_orient/global_orient + hand_pose/pose. "
            f"Found keys: {list(d.keys())}"
        )

    trans = _ensure_bt3(_as_torch(trans, device), "trans")
    root_orient = _ensure_bt3(_as_torch(root_orient, device), "root_orient")
    hand_pose = _ensure_bt45(_as_torch(hand_pose, device), "hand_pose")

    betas_t = None
    if betas is not None:
        betas_t = _as_torch(betas, device)
        if betas_t.ndim == 1:
            betas_t = betas_t[None, :]
        elif betas_t.ndim == 2:
            pass
        elif betas_t.ndim == 3:
            betas_t = betas_t[:, 0, :]
        else:
            raise ValueError(f"betas/shape must be (D) or (B,D) or (B,T,D); got {tuple(betas_t.shape)}")

    is_right_t = None
    if is_right is not None:
        is_right_t = _as_torch(is_right, device, dtype=torch.float32)
        if is_right_t.ndim == 1:
            if is_right_t.shape[0] == trans.shape[1]:
                is_right_t = is_right_t[None, :]
            else:
                is_right_t = is_right_t[:, None].expand(trans.shape[0], trans.shape[1])
        elif is_right_t.ndim == 2:
            pass
        else:
            raise ValueError(f"is_right must be (B,T) or (T,) or (B,); got {tuple(is_right_t.shape)}")
        is_right_t = (is_right_t >= 0.5).float()

    return ManoParams(trans=trans, root_orient=root_orient, hand_pose=hand_pose, betas=betas_t, is_right=is_right_t)


def _write_summary(out_dir: str, params: ManoParams) -> None:
    os.makedirs(out_dir, exist_ok=True)
    lines = []
    lines.append("MANO PARAMETER SUMMARY\n")
    lines.append(f"trans: {tuple(params.trans.shape)}  dtype={params.trans.dtype} device={params.trans.device}")
    lines.append(f"root_orient: {tuple(params.root_orient.shape)}")
    lines.append(f"hand_pose: {tuple(params.hand_pose.shape)}")
    if params.betas is not None:
        lines.append(f"betas: {tuple(params.betas.shape)}")
    else:
        lines.append("betas: <None>")
    if params.is_right is not None:
        lines.append(f"is_right: {tuple(params.is_right.shape)} (values: {sorted(set(_to_numpy(params.is_right).reshape(-1).tolist()))[:10]})")
    else:
        lines.append("is_right: <None> (assuming right hand)")

    # basic stats
    def stats(name: str, x: torch.Tensor):
        xnp = _to_numpy(x).reshape(-1)
        return f"{name}: min={xnp.min():.4f} max={xnp.max():.4f} mean={xnp.mean():.4f} std={xnp.std():.4f}"

    lines.append("")
    lines.append(stats("root_orient", params.root_orient))
    lines.append(stats("hand_pose", params.hand_pose))
    lines.append(stats("trans", params.trans))
    if params.betas is not None:
        lines.append(stats("betas", params.betas))

    with open(os.path.join(out_dir, "mano_params_summary.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")


def _plot_timeseries(out_dir: str, params: ManoParams) -> None:
    os.makedirs(out_dir, exist_ok=True)
    B, T, _ = params.trans.shape
    # Plot only the first track by default
    b = 0

    trans = _to_numpy(params.trans[b])  # (T,3)
    root = _to_numpy(params.root_orient[b])  # (T,3)
    pose = _to_numpy(params.hand_pose[b]).reshape(T, 15, 3)  # (T,15,3)

    # trans + root_orient
    def plot_3(ts, title, path):
        plt.figure(figsize=(10, 3))
        plt.plot(ts[:, 0], label="x")
        plt.plot(ts[:, 1], label="y")
        plt.plot(ts[:, 2], label="z")
        plt.title(title)
        plt.legend()
        plt.tight_layout()
        plt.savefig(path, dpi=150)
        plt.close()

    plot_3(trans, "trans (meters, as stored) over time", os.path.join(out_dir, "trans_timeseries.png"))
    plot_3(root, "root_orient axis-angle over time", os.path.join(out_dir, "root_orient_timeseries.png"))

    # Per-joint pose magnitude heatmap
    mag = np.linalg.norm(pose, axis=-1)  # (T,15)
    plt.figure(figsize=(10, 4))
    plt.imshow(mag.T, aspect="auto", interpolation="nearest")
    plt.xlabel("time")
    plt.ylabel("joint index (0..14)")
    plt.title("hand_pose axis-angle magnitude (rad) per joint")
    plt.colorbar()
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "hand_pose_magnitude_heatmap.png"), dpi=150)
    plt.close()

    # Betas
    if params.betas is not None:
        betas = _to_numpy(params.betas[b])  # (D,)
        plt.figure(figsize=(10, 3))
        plt.bar(np.arange(len(betas)), betas)
        plt.title("betas (shape) coefficients")
        plt.xlabel("beta index")
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "betas_bar.png"), dpi=150)
        plt.close()


def _make_joint_geometry(joints_xyz: np.ndarray, radius: float = 0.008) -> Tuple[list, list]:
    """
    Build trimesh geometries for joint spheres + bone cylinders.
    joints_xyz: (J,3) in same coordinate frame as the mesh.
    Returns (mesh_list, names_list)
    """
    meshes = []
    names = []

    # spheres
    for j in range(joints_xyz.shape[0]):
        sph = trimesh.creation.icosphere(subdivisions=2, radius=radius)
        sph.apply_translation(joints_xyz[j])
        sph.visual.vertex_colors = np.tile(np.array([255, 80, 80, 255], dtype=np.uint8), (len(sph.vertices), 1))
        meshes.append(sph)
        names.append(f"joint_{j:02d}")

    # bones
    for (a, b) in OPENPOSE_HAND_EDGES:
        if a >= joints_xyz.shape[0] or b >= joints_xyz.shape[0]:
            continue
        p0, p1 = joints_xyz[a], joints_xyz[b]
        seg = p1 - p0
        L = float(np.linalg.norm(seg))
        if L < 1e-8:
            continue
        cyl = trimesh.creation.cylinder(radius=radius * 0.45, height=L, sections=12)
        # Align cylinder (default along +Z) to segment direction
        z = np.array([0.0, 0.0, 1.0])
        v = seg / L
        axis = np.cross(z, v)
        axis_norm = float(np.linalg.norm(axis))
        if axis_norm < 1e-8:
            R = np.eye(3)
        else:
            axis = axis / axis_norm
            ang = float(np.arccos(np.clip(np.dot(z, v), -1.0, 1.0)))
            R = trimesh.transformations.rotation_matrix(ang, axis)[:3, :3]
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = (p0 + p1) / 2.0
        cyl.apply_transform(T)
        cyl.visual.vertex_colors = np.tile(np.array([80, 80, 255, 255], dtype=np.uint8), (len(cyl.vertices), 1))
        meshes.append(cyl)
        names.append(f"bone_{a:02d}_{b:02d}")

    return meshes, names


def render_frame(
    out_dir: str,
    verts: torch.Tensor,
    faces: torch.Tensor,
    joints: torch.Tensor,
    is_right: bool,
    img_res: int = 512,
    export_glb: bool = False,
    basename: str = "mano",
):
    os.makedirs(out_dir, exist_ok=True)

    v = _to_numpy(verts)
    j = _to_numpy(joints)
    f = _to_numpy(faces).astype(np.int64)

    # Keep the same convention as the repo viewer (pyrender is Y-up).
    # geometry.mesh.make_mesh applies this flip when yup=True, so we apply it
    # to BOTH vertices and joints here for consistency.
    flip = np.array([1.0, -1.0, -1.0], dtype=np.float32)
    v = v * flip[None, :]
    j = j * flip[None, :]

    # Base hand mesh
    base_color = (0.65, 0.75, 0.95) if is_right else (0.95, 0.65, 0.75)
    hand_mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
    hand_mesh.visual.vertex_colors = np.tile(np.array([*(np.array(base_color) * 255).astype(np.uint8), 255]), (len(hand_mesh.vertices), 1))

    joint_meshes, joint_names = _make_joint_geometry(j)
    all_meshes = [hand_mesh] + joint_meshes
    all_names = ["hand_mesh"] + joint_names

    if export_glb:
        save_meshes_to_glb(os.path.join(out_dir, f"{basename}.glb"), all_meshes, names=all_names)

    # Render with the repo's pyrender viewer.
    # NOTE: dyn-hamr/vis/viewer.py:init_viewer assumes intrins is not None (it scales it).
    # Provide a default [fx, fy, cx, cy] consistent with viewer.make_pyrender_camera fallback.
    W = H = int(img_res)
    focal = 0.5 * (H + W)
    intrins = torch.tensor([focal, focal, 0.5 * W, 0.5 * H], dtype=torch.float32)
    vis = init_viewer(img_size=(W, H), intrins=intrins, vis_scale=1.0, bg_paths=None, fps=30)
    vis.clear_meshes()
    vis.add_static_meshes(all_meshes, smooth=True)
    img = vis.render(render_bg=False, render_ground=True, render_cam=False, fac=1.0)
    vis.close()

    import imageio

    imageio.imwrite(os.path.join(out_dir, f"{basename}.png"), img[:, :, :3])


def main():
    parser = argparse.ArgumentParser()
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--phase_dir", type=str, help="Dyn-HaMR phase dir containing '*_results.npz' (e.g. .../smooth_fit/)")
    src.add_argument("--params", type=str, help="Standalone params file (.npz/.pkl) with MANO pose/shape params")

    parser.add_argument("--out_dir", type=str, required=True)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--frame", type=int, default=0, help="Frame index to render")
    parser.add_argument("--track", type=int, default=0, help="Track/person index to render")
    parser.add_argument("--img_res", type=int, default=512)
    parser.add_argument("--export_glb", action="store_true", help="Export a GLB scene (mesh + joints) as well")
    parser.add_argument(
        "--zero_global",
        action="store_true",
        help="If set, force MANO global translation/rotation to identity (trans=0, root_orient=0) before running MANO.",
    )
    parser.add_argument(
        "--center_wrist",
        action="store_true",
        help="If set, subtract wrist joint (joint 0) from all joints/vertices so the wrist is at the origin.",
    )
    parser.add_argument(
        "--print_joints",
        action="store_true",
        help="If set, print the MANO joint tensor and exit (useful for debugging coordinate conventions).",
    )
    parser.add_argument(
        "--dump_all_npz",
        action="store_true",
        help="If set, dump `mano_output_trackXX_frameYYYY.npz` for ALL tracks and ALL frames (no rendering).",
    )
    parser.add_argument(
        "--dump_openxr26",
        action="store_true",
        help="If set, also save OpenXR-26 joints (HAND_JOINT_NAMES order) into the dumped per-frame NPZs.",
    )
    parser.add_argument(
        "--openxr_metacarpal_alpha",
        type=float,
        default=0.3,
        help="OpenXR metacarpal placement alpha: wrist + a*(MCP - wrist).",
    )
    parser.add_argument(
        "--dump_openxr26_seq_npz",
        action="store_true",
        help="If set, save one `openxr26_joints.npz` containing joints_openxr26 with shape (B,T,26,3).",
    )

    parser.add_argument(
        "--cfg",
        type=str,
        default=os.path.join(THIS_DIR, "confs", "config.yaml"),
        help="Config used to locate MANO model assets (MODEL_PATH, MEAN_PARAMS, ...)",
    )

    args = parser.parse_args()

    device = torch.device(args.device)
    os.makedirs(args.out_dir, exist_ok=True)

    # Load config for MANO assets
    cfg = OmegaConf.load(args.cfg)
    cfg = resolve_cfg_paths(cfg)
    mano_cfg = {k.lower(): v for k, v in dict(cfg.MANO).items()}

    # Load params
    if args.phase_dir is not None:
        params = load_mano_params_from_dynhamr_phase(args.phase_dir, device=device)
    else:
        params = load_mano_params_from_file(args.params, device=device)

    if args.zero_global:
        # MANO conventions: `root_orient` is axis-angle (global orientation), `trans` is global translation.
        # Setting both to zero yields a canonical hand in the MANO frame (no global rotation/translation).
        params.trans = torch.zeros_like(params.trans)
        params.root_orient = torch.zeros_like(params.root_orient)

    _write_summary(args.out_dir, params)
    if params.trans.shape[1] > 1:
        _plot_timeseries(args.out_dir, params)

    # Instantiate MANO and run forward for all frames (matches repo convention)
    B, T, _ = params.trans.shape
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

    if args.center_wrist:
        # MANO joints are regressed in the model's canonical frame; the wrist joint is not guaranteed
        # to be at (0,0,0) even when trans=0 and root_orient=0.
        wrist = out["joints"][:, :, 0:1, :]  # (B,T,1,3)
        out["joints"] = out["joints"] - wrist
        out["vertices"] = out["vertices"] - wrist

    if args.dump_openxr26_seq_npz:
        joints_bt = _to_numpy(out["joints"])  # (B,T,J,3)
        if joints_bt.ndim != 4 or joints_bt.shape[-2:] != (joints_bt.shape[-2], 3):
            raise RuntimeError(f"Unexpected joints shape from MANO: {joints_bt.shape}")
        if joints_bt.shape[2] != 21:
            raise RuntimeError(
                f"Expected 21 MANO/OpenPose-style hand joints to convert to OpenXR-26; got J={joints_bt.shape[2]}"
            )
        B, T = joints_bt.shape[0], joints_bt.shape[1]
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

    if args.print_joints:
        print(out["joints"])
        return

    if args.dump_all_npz:
        # Dump all tracks + frames without rendering (fast path for downstream retargeting).
        for b in range(B):
            for t in range(T):
                verts_bt = out["vertices"][b, t]  # (V,3)
                joints_bt = out["joints"][b, t]  # (J,3)

                faces = out["r_faces"] if bool(is_right[b, t].item()) else out["l_faces"]
                faces = faces.to(device=device)

                extra = {}
                if args.dump_openxr26:
                    j21 = _to_numpy(joints_bt)
                    j26 = openpose21_to_openxr26_joints(j21, metacarpal_alpha=float(args.openxr_metacarpal_alpha))
                    extra["joints_openxr26"] = j26  # (26,3)
                    extra["joint_names_openxr26"] = np.asarray(HAND_JOINT_NAMES, dtype=object)

                np.savez(
                    os.path.join(args.out_dir, f"mano_output_track{b:02d}_frame{t:04d}.npz"),
                    vertices=_to_numpy(verts_bt),
                    joints=_to_numpy(joints_bt),
                    faces=_to_numpy(faces),
                    trans=_to_numpy(params.trans[b, t]),
                    root_orient=_to_numpy(params.root_orient[b, t]),
                    hand_pose=_to_numpy(params.hand_pose[b, t]),
                    betas=_to_numpy(params.betas[b]) if params.betas is not None else None,
                    is_right=float(is_right[b, t].item()),
                    **extra,
                )
        print(f"Wrote {B*T} MANO output npz files to: {args.out_dir}")
        return

    # Default behavior: render + dump a single (track, frame)
    b = int(np.clip(args.track, 0, B - 1))
    t = int(np.clip(args.frame, 0, T - 1))

    verts_bt = out["vertices"][b, t]  # (V,3)
    joints_bt = out["joints"][b, t]  # (J,3)

    faces = out["r_faces"] if bool(is_right[b, t].item()) else out["l_faces"]
    faces = faces.to(device=device)

    render_frame(
        args.out_dir,
        verts=verts_bt,
        faces=faces,
        joints=joints_bt,
        is_right=bool(is_right[b, t].item()),
        img_res=args.img_res,
        export_glb=args.export_glb,
        basename=f"mano_track{b:02d}_frame{t:04d}",
    )

    # Also dump raw MANOOutput-like arrays for downstream inspection
    np.savez(
        os.path.join(args.out_dir, f"mano_output_track{b:02d}_frame{t:04d}.npz"),
        vertices=_to_numpy(verts_bt),
        joints=_to_numpy(joints_bt),
        faces=_to_numpy(faces),
        trans=_to_numpy(params.trans[b, t]),
        root_orient=_to_numpy(params.root_orient[b, t]),
        hand_pose=_to_numpy(params.hand_pose[b, t]),
        betas=_to_numpy(params.betas[b]) if params.betas is not None else None,
        is_right=float(is_right[b, t].item()),
        **(
            {}
            if not args.dump_openxr26
            else {
                "joints_openxr26": openpose21_to_openxr26_joints(
                    _to_numpy(joints_bt), metacarpal_alpha=float(args.openxr_metacarpal_alpha)
                ),
                "joint_names_openxr26": np.asarray(HAND_JOINT_NAMES, dtype=object),
            }
        ),
    )


if __name__ == "__main__":
    main()


