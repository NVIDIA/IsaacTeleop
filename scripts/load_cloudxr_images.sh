#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e

CXR_RUNTIME_BUNDLE_VERSION="6.1.0-beta-rc1"
CXR_RUNTIME_TARBALL_NAME="cloudxr-runtime-server-webrtc-${CXR_RUNTIME_BUNDLE_VERSION}.tar.gz"
CXR_RUNTIME_IMAGE_NAME="cloudxr-runtime-webrtc:${CXR_RUNTIME_BUNDLE_VERSION}"

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

# Function to load images from tarball
load_images() {
    local tarball="$1"
    # Set default tarball filename if not specified
    if [ -z "$tarball" ]; then
        tarball="./deps/cloudxr/${CXR_RUNTIME_TARBALL_NAME}"
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

    # Validate the images using docker images --format and JSON parsing
    IMAGE_EXISTS=$(docker images --format json "${CXR_RUNTIME_IMAGE_NAME}" | wc -l)
    if [ "$IMAGE_EXISTS" -gt 0 ]; then
        echo "✓ Successfully validated images: ${CXR_RUNTIME_IMAGE_NAME}"
    else
        echo "✗ Failed to validate images: ${CXR_RUNTIME_IMAGE_NAME}"
        exit 1
    fi
}

load_images "$1"
