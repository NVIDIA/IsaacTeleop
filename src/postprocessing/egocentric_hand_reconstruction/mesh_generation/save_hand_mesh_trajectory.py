#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Export per-track hand meshes and joint trajectories in **final visualization space**:
MANO forward and left-hand x-reflection match `vis.output.prep_result_vis`.

Loads only `*_world_results.npz` plus optional `track_info.json` in the run directory
(parent of the phase folder, e.g. smooth_fit/). No `.hydra/config.yaml` required.

Runs inside the Dyn-HaMR Docker image (`docker/Dockerfile.dynhamr`), which installs
Dyn-HaMR at `/home/appuser/Dyn-HaMR/` and sets WORKDIR to `/home/appuser/Dyn-HaMR/dyn-hamr`,
so `body_model`, `util`, and `vis` resolve to the upstream packages. Launch via
`scripts/run_mesh_generation.sh` on the host, which forwards into the container.
"""

from __future__ import annotations

# chumpy 0.70 uses APIs removed in newer Python/NumPy; patch before pickle loads MANO.
import numpy as np

for _alias in ("bool", "int", "float", "complex", "object", "str", "unicode"):
    if not hasattr(np, _alias):
        setattr(
            np,
            _alias,
            getattr(__builtins__, _alias, None) or getattr(np, f"{_alias}_", None),
        )
import inspect  # noqa: E402

if not hasattr(inspect, "getargspec"):
    inspect.getargspec = inspect.getfullargspec

import argparse  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402

import torch  # noqa: E402

from body_model import MANO, run_mano  # noqa: E402
from util.tensor import detach_all, get_device  # noqa: E402
from vis.tools import smooth_results  # noqa: E402

DEFAULT_MANO_MODEL_DIR = "/home/appuser/Dyn-HaMR/_DATA/data/mano"


def load_vis_mask(log_dir: str, B: int, T: int) -> np.ndarray:
    """Per-track vis_mask from track_info.json if present, else all ones."""
    ti_path = os.path.join(log_dir, "track_info.json")
    if os.path.isfile(ti_path):
        try:
            with open(ti_path) as f:
                info = json.load(f)
            tracks = info.get("tracks", {})
            mask = np.ones((B, T), dtype=np.int8)
            for b, key in enumerate(sorted(tracks.keys(), key=int)[:B]):
                vm = tracks[key].get("vis_mask", None)
                if vm is not None:
                    arr = np.array(vm, dtype=bool)
                    length = min(len(arr), T)
                    mask[b, :length] = arr[:length].astype(np.int8)
            return mask
        except Exception:
            pass
    return np.ones((B, T), dtype=np.int8)


def try_load_fps(log_dir: str, default: float) -> float:
    ti_path = os.path.join(log_dir, "track_info.json")
    if not os.path.isfile(ti_path):
        return default
    try:
        with open(ti_path) as f:
            info = json.load(f)
        meta = info.get("meta", {})
        if "fps" in meta:
            return float(meta["fps"])
    except Exception:
        pass
    return default


def get_world_results_paths(phase_dir: str) -> dict[str, str]:
    """Map iteration id (e.g. 000300) -> path to *_world_results.npz."""
    res_files = sorted(glob.glob(os.path.join(phase_dir, "*_world_results.npz")))
    path_dict: dict[str, str] = {}
    for res_file in res_files:
        base = os.path.basename(res_file)
        parts = base.split("_")
        if len(parts) < 4:
            continue
        it, name, _ = parts[-3:]
        if name != "world":
            continue
        path_dict[it] = res_file
    return path_dict


def parse_seq_and_iter(npz_path: str) -> tuple[str, str]:
    """Infer seq name and iteration from e.g. ``oakd3_000300_world_results.npz``."""
    stem = os.path.splitext(os.path.basename(npz_path))[0]
    if "_world_results" in stem:
        prefix = stem.split("_world_results")[0]
        if "_" in prefix:
            seq, it = prefix.rsplit("_", 1)
            if it.isdigit():
                return seq, it
        return prefix, "000000"
    m = re.search(r"_(\d{4,})\.npz$", npz_path)
    it = m.group(1) if m else "000000"
    return stem, it


def numpy_world_to_state(npz_path: str, device: torch.device) -> dict:
    """Load world npz arrays as torch tensors on device (pose_body as B x T x 15 x 3)."""
    d = np.load(npz_path, allow_pickle=True)
    trans = torch.from_numpy(d["trans"].astype(np.float32)).to(device)
    root_orient = torch.from_numpy(d["root_orient"].astype(np.float32)).to(device)
    pb = d["pose_body"].astype(np.float32)
    if pb.ndim == 4:
        pose_body = torch.from_numpy(pb).to(device)
    else:
        pose_body = torch.from_numpy(pb.reshape(pb.shape[0], pb.shape[1], 15, 3)).to(
            device
        )
    is_right = torch.from_numpy(d["is_right"].astype(np.float32)).to(device)
    if "betas" in d.files:
        b = d["betas"].astype(np.float32)
        if b.ndim == 3:
            b = b[:, 0, :]
        betas = torch.from_numpy(b).to(device)
    else:
        betas = None
    return {
        "trans": trans,
        "root_orient": root_orient,
        "pose_body": pose_body,
        "is_right": is_right,
        "betas": betas,
    }


def _apply_vis_smoothing(res, temporal_smooth: bool, smooth_trans: bool):
    """Mirror vis smoothing; pose_body is B x T x 15 x 3."""
    res = detach_all(res)
    with torch.no_grad():
        if temporal_smooth:
            if smooth_trans:
                res["root_orient"], res["pose_body"], res["betas"], res["trans"] = (
                    smooth_results(
                        res["root_orient"],
                        res["pose_body"],
                        res["betas"],
                        res["is_right"],
                        res["trans"],
                    )
                )
            else:
                res["root_orient"], res["pose_body"], res["betas"], _ = smooth_results(
                    res["root_orient"],
                    res["pose_body"],
                    res["betas"],
                    res["is_right"],
                )
    return res


def export_trajectory_pack(
    *,
    seq_name: str,
    iter_name: str,
    npz_path: str,
    log_dir: str,
    device: torch.device,
    temporal_smooth: bool,
    smooth_trans: bool,
    out_path: str,
    fps: float,
    mano_model_dir: str,
):
    res = numpy_world_to_state(npz_path, device)
    B, T = res["trans"].shape[:2]
    if res["betas"] is None:
        res["betas"] = torch.zeros(B, 10, dtype=torch.float32, device=device)

    # MANOLayer sets create_* flags; do not pass create_hand_pose (duplicate kwarg).
    hand_model = MANO(
        batch_size=B * T,
        pose2rot=True,
        model_path=mano_model_dir,
        use_pca=False,
        num_pca_comps=45,
        flat_hand_mean=False,
        is_rhand=True,
    ).to(device)

    res = _apply_vis_smoothing(res, temporal_smooth, smooth_trans)
    pose_flat = res["pose_body"].reshape(B, T, -1)

    with torch.no_grad():
        mano_out = run_mano(
            hand_model,
            res["trans"],
            res["root_orient"],
            pose_flat,
            res["is_right"],
            res["betas"],
        )

    verts = mano_out["vertices"].detach().cpu().numpy().astype(np.float32)
    joints = mano_out["joints"].detach().cpu().numpy().astype(np.float32)
    is_right = mano_out["is_right"].detach().cpu().numpy().astype(np.int8)
    faces_left = mano_out["l_faces"].detach().cpu().numpy().astype(np.int32)
    faces_right = mano_out["r_faces"].detach().cpu().numpy().astype(np.int32)

    vis_mask = load_vis_mask(log_dir, B, T)
    track_ids = np.arange(B, dtype=np.int32)

    meta = {
        "format": "dyn_hamr_hand_mesh_traj_v1",
        "description": (
            "verts/joints are in the same world frame as run_vis after prep_result_vis. "
            "Use faces_left if is_right[b,t]==0 else faces_right."
        ),
        "source_npz": npz_path,
        "seq_name": seq_name,
        "iter": iter_name,
        "shapes": {
            "verts": list(verts.shape),
            "joints": list(joints.shape),
            "is_right": list(is_right.shape),
            "vis_mask": list(vis_mask.shape),
        },
        "fps": float(fps),
        "temporal_smooth": temporal_smooth,
        "smooth_trans": smooth_trans,
        "joint_index_wrist": 0,
    }

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(
        out_path,
        verts=verts,
        joints=joints,
        is_right=is_right,
        faces_left=faces_left,
        faces_right=faces_right,
        vis_mask=vis_mask,
        track_ids=track_ids,
        fps=np.float32(fps),
    )
    meta_path = out_path.replace(".npz", "_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Wrote {out_path}")
    print(f"Wrote {meta_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Build hand mesh trajectory npz from *_world_results.npz (+ track_info.json)."
    )
    parser.add_argument(
        "--npz",
        default=None,
        help="Path to *_world_results.npz (if omitted, use --log-dir + --phase).",
    )
    parser.add_argument(
        "--log-dir",
        "--log_dir",
        dest="log_dir",
        default=None,
        help="Run directory containing track_info.json (parent of smooth_fit/). "
        "Default when using --npz: parent of the phase folder.",
    )
    parser.add_argument(
        "--phase",
        default="smooth_fit",
        help="Phase subdir under --log-dir when resolving npz (default: smooth_fit).",
    )
    parser.add_argument(
        "--iter",
        default=None,
        help="Checkpoint id (e.g. 000300). Default: latest *_world_results in phase dir.",
    )
    parser.add_argument(
        "-o",
        "--out",
        default=None,
        help="Output .npz path (default: beside source npz: <seq>_hand_mesh_traj_<iter>.npz).",
    )
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="FPS in output (default: 30 or from track_info).",
    )
    parser.add_argument(
        "--no_temporal_smooth",
        action="store_true",
        help="Disable OneEuro smoothing.",
    )
    parser.add_argument(
        "--no_smooth_trans",
        action="store_true",
        help="Smooth pose only, not translation.",
    )
    parser.add_argument(
        "--mano-model-dir",
        "--mano_model_dir",
        dest="mano_model_dir",
        default=os.environ.get("MANO_MODEL_DIR", DEFAULT_MANO_MODEL_DIR),
        help=(
            "Directory containing MANO_RIGHT.pkl. "
            f"Default: $MANO_MODEL_DIR or {DEFAULT_MANO_MODEL_DIR}."
        ),
    )
    args = parser.parse_args()
    temporal_smooth = not args.no_temporal_smooth
    smooth_trans = not args.no_smooth_trans
    device = get_device(args.gpu)

    npz_path = args.npz
    log_dir = args.log_dir

    if npz_path:
        npz_path = os.path.abspath(npz_path)
        if not os.path.isfile(npz_path):
            print(f"Not found: {npz_path}", file=sys.stderr)
            sys.exit(1)
        if log_dir is None:
            phase_dir = os.path.dirname(npz_path)
            log_dir = os.path.dirname(phase_dir)
        else:
            log_dir = os.path.abspath(log_dir)
        seq_name, iter_name = parse_seq_and_iter(npz_path)
    else:
        if not args.log_dir:
            print(
                "Error: pass --npz or --log-dir (with optional --phase).",
                file=sys.stderr,
            )
            sys.exit(1)
        log_dir = os.path.abspath(args.log_dir)
        phase_dir = os.path.join(log_dir, args.phase)
        if not os.path.isdir(phase_dir):
            print(f"Missing phase dir: {phase_dir}", file=sys.stderr)
            sys.exit(1)
        path_dict = get_world_results_paths(phase_dir)
        if not path_dict:
            print(f"No *_world_results.npz in {phase_dir}", file=sys.stderr)
            sys.exit(1)
        if args.iter is not None:
            it = args.iter
            if it not in path_dict:
                print(f"No iteration {it} in {phase_dir}", file=sys.stderr)
                sys.exit(1)
        else:
            it = sorted(path_dict.keys())[-1]
        npz_path = path_dict[it]
        seq_name, iter_name = parse_seq_and_iter(npz_path)
        if args.iter is not None:
            iter_name = args.iter

    default_fps = try_load_fps(log_dir, 30.0)
    fps = args.fps if args.fps is not None else default_fps

    out_path = args.out
    if out_path is None:
        out_path = os.path.join(
            os.path.dirname(npz_path),
            f"{seq_name}_hand_mesh_traj_{iter_name}.npz",
        )

    export_trajectory_pack(
        seq_name=seq_name,
        iter_name=iter_name,
        npz_path=npz_path,
        log_dir=log_dir,
        device=device,
        temporal_smooth=temporal_smooth,
        smooth_trans=smooth_trans,
        out_path=os.path.abspath(out_path),
        fps=fps,
        mano_model_dir=args.mano_model_dir,
    )


if __name__ == "__main__":
    main()
