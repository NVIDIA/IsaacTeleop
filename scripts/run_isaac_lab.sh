#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

# Source shared CloudXR environment setup
source scripts/setup_cloudxr_env.sh

if [ ! -f "$XR_RUNTIME_JSON" ]; then
    echo "Error: $XR_RUNTIME_JSON not found. Please run ./scripts/run_cloudxr.sh first."
    exit 1
fi

# Run the Isaac Lab script
if [ -z "${ISAACLAB_PATH:-}" ]; then
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

# Resolve the IsaacTeleop repo root (directory containing this script's parent)
# before cd'ing away, so we can point VIRTUAL_ENV at the correct venv.
ISAACTELEOP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ISAACLAB_PATH"

# Use venv_isaacteleop (has isaacsim + isaaclab), falling back to env_isaaclab.
if [ -f "${ISAACTELEOP_ROOT}/venv_isaacteleop/bin/python" ]; then
    export VIRTUAL_ENV="${ISAACTELEOP_ROOT}/venv_isaacteleop"
elif [ -f "${ISAACTELEOP_ROOT}/env_isaaclab/bin/python" ]; then
    export VIRTUAL_ENV="${ISAACTELEOP_ROOT}/env_isaaclab"
elif [ -f "${ISAACLAB_PATH}/env_isaaclab/bin/python" ]; then
    export VIRTUAL_ENV="${ISAACLAB_PATH}/env_isaaclab"
else
    unset VIRTUAL_ENV
fi

if [ -n "${ISAACSIM_PATH:-}" ] && [ -f "$ISAACSIM_PATH/setup_conda_env.sh" ]; then
    # This is only necessary if Isaac Sim is installed via source code:
    # https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/source_installation.html
    if [ -n "${CONDA_PREFIX:-}" ]; then
        echo "Setting up Isaac Sim conda environment..."
        source "$ISAACSIM_PATH/setup_conda_env.sh"
    fi
fi

./isaaclab.sh -p scripts/environments/teleoperation/teleop_se3_agent.py \
    --task Isaac-PickPlace-G1-InspireFTP-Abs-v0 \
    --num_envs 1 \
    --teleop_device handtracking \
    --device cpu \
    --enable_pinocchio \
    --info \
    --xr
