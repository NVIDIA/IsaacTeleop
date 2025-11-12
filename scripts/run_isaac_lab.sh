#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e

export XDG_RUNTIME_DIR=$HOME/.cloudxr/run
export XR_RUNTIME_JSON=$HOME/.cloudxr/share/openxr/1/openxr_cloudxr.json

if [ ! -f $XR_RUNTIME_JSON ]; then
    echo "Error: $XR_RUNTIME_JSON not found. Please run ./scripts/run_cloudxr.sh first."
    exit 1
fi

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

python examples/lab/isaac_lab_teleop.py \
    --task Isaac-PickPlace-Locomanipulation-G1-Abs-v0 \
    --num_envs 1 \
    --teleop_device quest3_controllers \
    --device cpu \
    --enable_pinocchio \
    --info
