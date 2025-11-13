#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e

BUNDLE_VERSION="teleopcore-0.1.0"

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

# Function to load images from tarball
load_images() {
    local tarball="$1"
    # Set default tarball filename if not specified
    if [ -z "$tarball" ]; then
        tarball="./deps/cloudxr/${BUNDLE_VERSION}-cxr-images.tar.gz"
        echo "Loading CloudXR images from default location: $tarball"
    fi

    if [ ! -f "$tarball" ]; then
        echo "Error: File not found: $tarball"
        exit 1
    fi

    echo "Loading Docker images from: $tarball"
    gunzip -c "$tarball" | docker load
    if [ $? -eq 0 ]; then
        echo "✓ Successfully loaded images from: $tarball"
    else
        echo "✗ Failed to load images"
        exit 1
    fi
}

load_images "$1"