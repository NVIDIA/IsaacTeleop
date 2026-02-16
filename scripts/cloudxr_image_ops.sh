#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

PUBLIC_REGISTRY="nvcr.io/nvidia/cloudxr-runtime-early-access"
PRIVATE_REGISTRY="nvcr.io/0566138804516934/cloudxr-dev/cloudxr-runtime"

check_nvcr_login() {
    if grep -q "nvcr.io" ~/.docker/config.json 2>/dev/null; then
        return 0
    else
        echo "Login required for NVIDIA Registry..."
        echo "Please follow the instructions at https://org.ngc.nvidia.com/setup/api-keys"
        exit 1
    fi
}

# Function to save the CloudXR Runtime image to tarball
save_image() {
    local container_tag="$1"
    if [ -z "$container_tag" ]; then
        echo "Error: container_tag is required"
        show_usage
        exit 1
    fi

    # Pull the image first
    pull_image "$container_tag"

    local local_name="cloudxr-runtime:$container_tag"
    local tarball="deps/cloudxr/cloudxr-runtime-${container_tag}.tar.gz"

    echo ""
    echo "Saving Docker image to: $tarball"
    if docker save "$local_name" | gzip > "$tarball"; then
        echo "✓ Successfully saved image to: $tarball"
        echo "File size: $(du -h "$tarball" | cut -f1)"
        echo ""
        echo "Image saved with name:"
        echo "  - $local_name"
    else
        echo "✗ Failed to save image"
        exit 1
    fi
}

# Function to pull the CloudXR Runtime image from registry
pull_image() {
    local container_tag="$1"
    if [ -z "$container_tag" ]; then
        echo "Error: container_tag is required"
        show_usage
        exit 1
    fi

    check_nvcr_login

    local public_image="$PUBLIC_REGISTRY:$container_tag"
    local private_image="$PRIVATE_REGISTRY:$container_tag"
    local local_name="cloudxr-runtime:$container_tag"
    local source_image=""

    echo "Attempting to pull Docker image..."

    # Try public registry first
    echo "Trying public registry: $public_image"
    if docker pull "$public_image" 2>/dev/null; then
        echo "✓ Successfully pulled from public registry: $public_image"
        source_image="$public_image"
    else
        echo "  Public registry pull failed, trying private registry..."
        # Try private registry
        echo "Trying private registry: $private_image"
        if docker pull "$private_image"; then
            echo "✓ Successfully pulled from private registry: $private_image"
            source_image="$private_image"
        else
            echo "✗ Failed to pull from both registries"
            exit 1
        fi
    fi

    echo "Tagging: $source_image -> $local_name"
    if docker tag "$source_image" "$local_name"; then
        echo "✓ Successfully tagged: $local_name"
        # Remove the source tag (rename)
        docker rmi "$source_image" >/dev/null 2>&1 || true
    else
        echo "✗ Failed to tag: $local_name"
        exit 1
    fi

    echo ""
    echo "Image pulled and tagged as: $local_name"
}

# Function to load the CloudXR Runtime image from a tarball
load_image() {
    local container_tag="$1"
    if [ -z "$container_tag" ]; then
        echo "Error: container_tag is required"
        show_usage
        exit 1
    fi

    local tarball="deps/cloudxr/cloudxr-runtime-${container_tag}.tar.gz"

    if [ ! -f "$tarball" ]; then
        echo "Error: File not found: $tarball"
        exit 1
    fi

    echo "Loading Docker image from: $tarball"
    if gunzip -c "$tarball" | docker load; then
        echo "✓ Successfully loaded image from: $tarball"
    else
        echo "✗ Failed to load image"
        exit 1
    fi
}

# Function to display usage
show_usage() {
    echo "Usage: $0 [OPTION] <container_tag>"
    echo ""
    echo "Options:"
    echo "  --pull <container_tag>     Pull image from registry (tries public, then private)"
    echo "  --save <container_tag>     Pull and save image to a tarball"
    echo "  --load <container_tag>     Load image from a tarball"
    echo "  --help                     Display this help message"
    echo ""
    echo "Registries (checked in order during --pull/--save):"
    echo "  1. Public:  $PUBLIC_REGISTRY"
    echo "  2. Private (NVIDIA internal use only): $PRIVATE_REGISTRY"
}

# Main script logic
if [ $# -eq 0 ]; then
    echo "Error: No arguments provided"
    show_usage
    exit 1
fi

case "$1" in
    --pull)
        pull_image "$2"
        ;;
    --save)
        save_image "$2"
        ;;
    --load)
        load_image "$2"
        ;;
    --help)
        show_usage
        ;;
    *)
        echo "Error: Unknown option: $1"
        show_usage
        exit 1
        ;;
esac
