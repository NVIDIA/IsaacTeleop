# MANO Hand Retargeting

## Setup

```bash
./scripts/setup_venv_isaac.sh
source venv_isaac/bin/activate
```

The pinned dependency list is in `requirements-venv_isaac.txt`.


Set your IsaacLab checkout path (needed for replay scripts that launch Isaac Sim via `isaaclab.sh`):

```bash
export ISAACLAB_PATH=/home/lduan/Documents/IsaacLab
```

Work from this directory:

```bash
cd examples/mano_hand_retargeter/
```

## 1) Export OpenXR-26 joints (no global translation/orientation)

```bash
python export_openxr26_from_world_results.py \
  --world_results ./hand_reconstruction_results/meta_776_30fps_000300_world_results.npz \
  --out_dir ./outputs/retarget_meta/openxr26_single_hand_zero_global \
  --zero_global \
  --split_by_handedness
```

Outputs:
- `./outputs/retarget_meta/openxr26_single_hand_zero_global/openxr26_joints_left.npz`
- `./outputs/retarget_meta/openxr26_single_hand_zero_global/openxr26_joints_right.npz`

## 2) Find optimized input hand rotation (grid search)

Empirically best rotations:
- **Right**: `0,-90,0`
- **Left**: `0,90,0`

Right-hand grid search:

```bash
python3 retarget_openxr26_with_g1_upper_body.py \
  --input ./outputs/retarget_meta/openxr26_single_hand_zero_global/openxr26_joints_right.npz \
  --output ./outputs/retarget_meta/openxr26_single_hand_zero_global/g1_cmds_right \
  --left-hand-urdf ./_DATA/G1_left_hand.urdf \
  --right-hand-urdf ./_DATA/G1_right_hand.urdf \
  --grid-search-rot \
  --grid-hand right \
  --grid-step 10 \
  --grid-pivot wrist \
  --grid-out-dir ./outputs/retarget_meta/openxr26_single_hand_zero_global/rot_grid_search_multi_right \
  --grid-topk-viz 5 \
  --seq-track 0
```

Left-hand grid search:

```bash
python3 retarget_openxr26_with_g1_upper_body.py \
  --input ./outputs/retarget_meta/openxr26_single_hand_zero_global/openxr26_joints_left.npz \
  --output ./outputs/retarget_meta/openxr26_single_hand_zero_global/g1_cmds_left \
  --left-hand-urdf ./_DATA/G1_left_hand.urdf \
  --right-hand-urdf ./_DATA/G1_right_hand.urdf \
  --grid-search-rot \
  --grid-hand left \
  --grid-step 10 \
  --grid-pivot wrist \
  --grid-out-dir ./outputs/retarget_meta/openxr26_single_hand_zero_global/rot_grid_search_multi_left \
  --grid-topk-viz 5 \
  --seq-track 0
```

## 3) Apply rotation and retarget (save trajectory NPZ)

Left hand:

```bash
python3 retarget_openxr26_with_g1_upper_body.py \
  --input ./outputs/retarget_meta/openxr26_single_hand_zero_global/openxr26_joints_left.npz \
  --output ./outputs/retarget_meta/openxr26_single_hand_zero_global/g1_cmds_left \
  --left-hand-urdf ./_DATA/G1_left_hand.urdf \
  --right-hand-urdf ./_DATA/G1_right_hand.urdf \
  --single-hand left \
  --apply-rot 0,90,0 \
  --apply-rot-hand left \
  --apply-rot-pivot wrist \
  --seq-track 0 \
  --save-traj-npz ./outputs/retarget_meta/openxr26_single_hand_zero_global/left_hand_traj_optrot.npz
```

Right hand:

```bash
python3 retarget_openxr26_with_g1_upper_body.py \
  --input ./outputs/retarget_meta/openxr26_single_hand_zero_global/openxr26_joints_right.npz \
  --output ./outputs/retarget/openxr26_single_hand_zero_global/g1_cmds_right \
  --left-hand-urdf ./_DATA/G1_left_hand.urdf \
  --right-hand-urdf ./_DATA/G1_right_hand.urdf \
  --single-hand right \
  --apply-rot 0,-90,0 \
  --apply-rot-hand right \
  --apply-rot-pivot wrist \
  --seq-track 0 \
  --save-traj-npz ./outputs/retarget_meta/openxr26_single_hand_zero_global/right_hand_traj_optrot.npz
```

## 4) Replay robot hand (no world trajectory)

Isaac Sim/Kit can be sensitive to pickled object arrays in `.npz`. Convert the saved trajectories to a no-pickle format:

```bash
python convert_traj_npz_no_pickle.py \
  --in  ./outputs/retarget_meta/openxr26_single_hand_zero_global/left_hand_traj_optrot.npz \
  --out ./outputs/retarget_meta/openxr26_single_hand_zero_global/left_hand_traj_optrot_nopickle.npz \
&& \
python convert_traj_npz_no_pickle.py \
  --in  ./outputs/retarget_meta/openxr26_single_hand_zero_global/right_hand_traj_optrot.npz \
  --out ./outputs/retarget_meta/openxr26_single_hand_zero_global/right_hand_traj_optrot_nopickle.npz
```

Replay:

```bash
../../scripts/run_hand_retarget_no_global.sh
```

## 5) Apply world orientation + translation to the trajectories

Left:

```bash
python apply_world_pose_to_traj_npz.py \
  --traj_npz_in  ./outputs/retarget_meta/openxr26_single_hand_zero_global/left_hand_traj_optrot.npz \
  --traj_npz_out ./outputs/retarget_meta/openxr26_single_hand_zero_global/left_hand_traj_world_prerot.npz \
  --world_results ./hand_reconstruction_results/meta_776_30fps_000300_world_results.npz \
  --hand left \
  --split_npz ./outputs/retarget_meta/openxr26_single_hand_zero_global/openxr26_joints_left.npz \
  --seq_track 0 \
  --apply_to both \
  --to_isaac_world \
  --pre_rot 0,0,0
```

Right:

```bash
python apply_world_pose_to_traj_npz.py \
  --traj_npz_in  ./outputs/retarget_meta/openxr26_single_hand_zero_global/right_hand_traj_optrot.npz \
  --traj_npz_out ./outputs/retarget_meta/openxr26_single_hand_zero_global/right_hand_traj_world_prerot.npz \
  --world_results ./hand_reconstruction_results/meta_776_30fps_000300_world_results.npz \
  --hand right \
  --split_npz ./outputs/retarget_meta/openxr26_single_hand_zero_global/openxr26_joints_right.npz \
  --seq_track 0 \
  --apply_to both \
  --to_isaac_world \
  --pre_rot 0,0,0
```

## 6) Replay robot hand (with world trajectory)

Convert to no-pickle:

```bash
python convert_traj_npz_no_pickle.py \
  --in  ./outputs/retarget_meta/openxr26_single_hand_zero_global/left_hand_traj_world_prerot.npz \
  --out ./outputs/retarget_meta/openxr26_single_hand_zero_global/left_hand_traj_world_prerot_nopickle.npz \
&& \
python convert_traj_npz_no_pickle.py \
  --in  ./outputs/retarget_meta/openxr26_single_hand_zero_global/right_hand_traj_world_prerot.npz \
  --out ./outputs/retarget_meta/openxr26_single_hand_zero_global/right_hand_traj_world_prerot_nopickle.npz
```

Replay:

```bash
../../scripts/run_hand_retarget_global.sh
```

Replay with object:

```bash
../../scripts/run_hand_retarget_global_with_object.sh
```

