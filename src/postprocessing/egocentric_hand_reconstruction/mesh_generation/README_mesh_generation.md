<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Hand Mesh Generation

Export per-track MANO hand meshes and joint trajectories from Dyn-HaMR reconstruction results.
Produces `.npz` files containing vertices, joints, faces, and visibility masks in the final
visualisation world frame — ready to load and plot without a MANO model or any handedness flip.

Runs inside the Dyn-HaMR Docker image (`docker/Dockerfile.dynhamr`), which already provides
Dyn-HaMR, MANO, and the full Python environment. There is no host-side Python path.

## Prerequisites

### 1. Build the Dyn-HaMR image

```bash
./docker/dynhamr.sh build
```

### 2. MANO model

Place `MANO_RIGHT.pkl` at `outputs/MANO_RIGHT.pkl` (same file used by the reconstruction
pipeline). Download from https://mano.is.tue.mpg.de/ (free registration). The container's
`setup_dynhamr.sh` copies it into `/home/appuser/Dyn-HaMR/_DATA/data/mano/` on first run.

### 3. Dyn-HaMR results

Run the full reconstruction pipeline first so each run has `smooth_fit/*_world_results.npz`:

```
outputs/logs/video-custom/<date>/<seq>/
├── track_info.json          # optional; per-track vis_mask
└── smooth_fit/
    └── *_world_results.npz
```

Mesh export only reads that npz and optional `track_info.json` beside it; no `.hydra/` required.

## Running

```bash
./scripts/run_mesh_generation.sh
```

Scans `outputs/` by default (override with `OUTPUTS_DIR=…`), finds every run directory
containing `<PHASE>/*_world_results.npz` (default `PHASE=smooth_fit`), and runs the export
once per run on the latest world checkpoint.

### Environment variables

| Variable             | Default        | Description                                              |
|----------------------|----------------|----------------------------------------------------------|
| `OUTPUTS_DIR`        | `<repo>/outputs` | Host directory mounted into the container at `/home/appuser/outputs` |
| `PHASE`              | `smooth_fit`   | Phase subdir to read results from                        |
| `GPU`                | `0`            | GPU index inside the container                           |
| `NO_TEMPORAL_SMOOTH` | `0`            | Set to `1` to disable OneEuro smoothing (raw poses)      |
| `NO_SMOOTH_TRANS`    | `0`            | Set to `1` to smooth pose only, not translation          |

Example:

```bash
GPU=1 NO_TEMPORAL_SMOOTH=1 ./scripts/run_mesh_generation.sh
```

### Running a single input manually

To process one `*_world_results.npz` file directly, drop into the container and call the
Python script with its flags:

```bash
./docker/dynhamr.sh run bash -c "
    bash /home/appuser/setup_dynhamr.sh >/dev/null
    python /home/appuser/Dyn-HaMR/dyn-hamr/save_hand_mesh_trajectory.py \
        --npz /home/appuser/outputs/logs/.../smooth_fit/<seq>_000300_world_results.npz
"
```

Flags:

| Flag                  | Default        | Description                                              |
|-----------------------|----------------|----------------------------------------------------------|
| `--npz`               | *(optional)*   | Path to `*_world_results.npz`; if omitted, use `--log-dir` + `--phase` |
| `--log-dir` / `--log_dir` | *(with phase)* | Run directory containing `track_info.json` (parent of `smooth_fit/`) |
| `--phase`             | `smooth_fit`   | Subdir under `--log-dir` that holds `*_world_results.npz` |
| `--iter`              | latest         | Checkpoint ID when resolving via `--log-dir` (e.g. `000300`) |
| `--fps`               | 30 or from `track_info` | FPS written into the output npz                     |
| `-o / --out`          | auto           | Output path; default beside source npz: `<seq>_hand_mesh_traj_<iter>.npz` |
| `--gpu`               | `0`            | GPU index                                                |
| `--no_temporal_smooth`| off            | Disable OneEuro smoothing                                |
| `--no_smooth_trans`   | off            | Smooth pose only, not translation                        |
| `--mano-model-dir`    | `/home/appuser/Dyn-HaMR/_DATA/data/mano` | Directory containing `MANO_RIGHT.pkl` (or set `MANO_MODEL_DIR`) |

## Output

For each processed log dir, two files are written alongside the world results:

```
<log_dir>/smooth_fit/
├── <seq>_hand_mesh_traj_<iter>.npz
└── <seq>_hand_mesh_traj_<iter>_meta.json
```

### `.npz` arrays

| Array         | Shape              | dtype   | Description                                         |
|---------------|--------------------|---------|-----------------------------------------------------|
| `verts`       | `(B, T, 778, 3)`   | float32 | Mesh vertices in world frame                        |
| `joints`      | `(B, T, 21, 3)`    | float32 | Joint positions; index 0 = wrist                    |
| `is_right`    | `(B, T)`           | int8    | 1 = right hand, 0 = left hand                       |
| `faces_left`  | `(F, 3)`           | int32   | Triangle face indices for left-hand meshes          |
| `faces_right` | `(F, 3)`           | int32   | Triangle face indices for right-hand meshes         |
| `vis_mask`    | `(B, T)`           | int8    | 1 = visible, 0 = occluded, -1 = out of scene        |
| `track_ids`   | `(B,)`             | int     | Track IDs                                           |
| `fps`         | scalar             | float32 | Video frame rate                                    |

`B` = number of tracks, `T` = sequence length in frames.

### Loading example

```python
import numpy as np

data = np.load("my_seq_hand_mesh_traj_000300.npz")
verts    = data["verts"]      # (B, T, 778, 3)
joints   = data["joints"]     # (B, T, 21, 3)
is_right = data["is_right"]   # (B, T)
faces_right = data["faces_right"]
faces_left  = data["faces_left"]

# Pick faces for each track based on handedness
for b in range(verts.shape[0]):
    faces = faces_right if is_right[b, 0] else faces_left
    # verts[b], joints[b], faces are ready to render/plot
```
