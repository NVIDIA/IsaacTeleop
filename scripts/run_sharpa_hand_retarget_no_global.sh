#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e

# Run the Isaac Lab script
if [ -z "$ISAACLAB_PATH" ]; then
    echo "Error: ISAACLAB_PATH environment variable is not set. Please set it to the path of the Isaac Lab repository."
    exit 1
fi

if [ ! -d "$ISAACLAB_PATH" ]; then
    echo "Error: ISAACLAB_PATH '$ISAACLAB_PATH' does not exist or is not a directory."
    exit 1
fi

if [ ! -f "$ISAACLAB_PATH/isaaclab.sh" ]; then
    echo "Error: Isaac Lab script not found in $ISAACLAB_PATH."
    echo "Please make sure you have set the ISAACLAB_PATH environment variable to the path of the Isaac Lab repository."
    exit 1
fi

cd $ISAACLAB_PATH || exit 1

# Make IsaacLab python package discoverable for any direct python subprocesses.
# Your layout: $ISAACLAB_PATH/source/isaaclab/isaaclab/...
export PYTHONPATH="$ISAACLAB_PATH/source/isaaclab:${PYTHONPATH}"

# IsaacLab's `isaaclab.sh` prefers CONDA_PREFIX over VIRTUAL_ENV when choosing Python.
# If conda base is active, it will pick conda's python (often missing `isaacsim`), causing:
#   ModuleNotFoundError: No module named 'isaacsim'
#
# We temporarily hide conda env vars for this invocation, and prefer this repo's venv if present.
_saved_CONDA_PREFIX="${CONDA_PREFIX-}"
_saved_CONDA_DEFAULT_ENV="${CONDA_DEFAULT_ENV-}"
_saved_CONDA_SHLVL="${CONDA_SHLVL-}"
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL

# Prefer this repo's venv_isaac if it exists (so `isaacsim` pip package is available).
if [ -z "${VIRTUAL_ENV-}" ] && [ -f "/home/lduan/Documents/IsaacTeleop/venv_isaac/bin/activate" ]; then
    # shellcheck disable=SC1091
    source /home/lduan/Documents/IsaacTeleop/venv_isaac/bin/activate
fi

if [ -f "$ISAACSIM_PATH/setup_conda_env.sh" ]; then
    # This is only necessary if Isaac Sim is installed via source code:
    # https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/source_installation.html
    if [ -n "$CONDA_PREFIX" ]; then
        echo "Setting up Isaac Sim conda environment..."
        source $ISAACSIM_PATH/setup_conda_env.sh
    fi
fi

"$ISAACLAB_PATH/isaaclab.sh" -p /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/sharpahand_replay_traj.py \
    --hand both \
    --traj_npz_left  /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/outputs/sharpa_retarget_meta/openxr26_single_hand_zero_global/left_hand_traj_optrot_nopickle.npz \
    --traj_npz_right /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/outputs/sharpa_retarget_meta/openxr26_single_hand_zero_global/right_hand_traj_optrot_nopickle.npz \
    --left-hand-urdf /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/_DATA/Sharpa_HA4_URDF_USD_V2.2.3/Sharpa_HA4_URDF_USD_V2.2.3/src/left_sharpa_ha4/left_sharpa_ha4_v2_1.urdf \
    --right-hand-urdf /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/_DATA/Sharpa_HA4_URDF_USD_V2.2.3/Sharpa_HA4_URDF_USD_V2.2.3/src/right_sharpa_ha4/right_sharpa_ha4_v2_1.urdf \
    --mesh_dir_left /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/_DATA/Sharpa_HA4_URDF_USD_V2.2.3/Sharpa_HA4_URDF_USD_V2.2.3/src/left_sharpa_ha4/meshes \
    --mesh_dir_right /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/_DATA/Sharpa_HA4_URDF_USD_V2.2.3/Sharpa_HA4_URDF_USD_V2.2.3/src/right_sharpa_ha4/meshes \
    --spawn_height 0.3 \
    --hand_spacing 0.18 \
    --loop

# Restore conda env vars (best effort)
if [ -n "${_saved_CONDA_PREFIX}" ]; then export CONDA_PREFIX="${_saved_CONDA_PREFIX}"; fi
if [ -n "${_saved_CONDA_DEFAULT_ENV}" ]; then export CONDA_DEFAULT_ENV="${_saved_CONDA_DEFAULT_ENV}"; fi
if [ -n "${_saved_CONDA_SHLVL}" ]; then export CONDA_SHLVL="${_saved_CONDA_SHLVL}"; fi
unset _saved_CONDA_PREFIX _saved_CONDA_DEFAULT_ENV _saved_CONDA_SHLVL
    
# "$ISAACLAB_PATH/isaaclab.sh" -p /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/unitree_trihand_replay_traj.py \
#      --hand both \
#      --traj_npz_left  /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/outputs/retarget_meta/openxr26_single_hand_zero_global/left_hand_traj_world_prerot_nopickle.npz \
#      --traj_npz_right /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/outputs/retarget_meta/openxr26_single_hand_zero_global/right_hand_traj_world_prerot_nopickle.npz \
#      --use_wrist_pose \
#      --loop \
#      --ground_z -100 \
#      --mesh_dir /home/lduan/Documents/IsaacTeleop/examples/mano_hand_retargeter/hand_urdf/meshes \
#      --camera_target 0,0,0 \
#      --camera_dir=-10,20,-10 \
#      --camera_dist 1.0