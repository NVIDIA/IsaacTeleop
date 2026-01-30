#!/usr/bin/env python3
"""
Convert a trajectory NPZ produced by `retarget_openxr26_with_g1_upper_body.py` to a "no-pickle" format.

Why:
- Isaac Sim/Kit runs with a bundled NumPy. Pickled object arrays (dtype=object) can crash or fail to
  unpickle depending on the NumPy version that wrote the file.
- The trajectory files in this repo often store only *strings* (e.g., `frame_files`, `*_dof_names`)
  as object arrays; this tool rewrites those arrays as plain string arrays (`dtype=str`).

Usage:
  python convert_traj_npz_no_pickle.py --in left_hand_traj_optrot.npz --out left_hand_traj_optrot_nopickle.npz
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", required=True, help="Input trajectory .npz (may contain object arrays).")
    ap.add_argument("--out", dest="out_path", required=True, help="Output trajectory .npz (no object arrays).")
    args = ap.parse_args()

    in_path = Path(args.in_path).expanduser().resolve()
    out_path = Path(args.out_path).expanduser().resolve()
    if not in_path.is_file():
        raise FileNotFoundError(in_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    z = np.load(str(in_path), allow_pickle=True)
    out: dict[str, np.ndarray] = {}
    for k in z.files:
        arr = z[k]
        if getattr(arr, "dtype", None) is not None and arr.dtype == object:
            out[k] = np.asarray(arr, dtype=str)
        else:
            out[k] = np.asarray(arr)

    # Ensure no object arrays remain
    bad = [k for k, v in out.items() if getattr(v, "dtype", None) == object]
    if bad:
        raise RuntimeError(f"Conversion failed; still has object arrays for keys: {bad}")

    np.savez_compressed(out_path, **out)
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()


