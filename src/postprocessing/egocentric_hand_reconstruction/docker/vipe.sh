#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Configuration
IMAGE_NAME="ego_vipe:latest"
CONTAINER_NAME="ego-vipe"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERFILE="${PROJECT_ROOT}/docker/Dockerfile.vipe"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

build_image() {
    local no_cache_flag=""
    if [ "$1" == "--clean" ]; then
        no_cache_flag="--no-cache"
        print_info "Clean build requested (--no-cache)"
    fi

    print_info "Building ViPE image: ${IMAGE_NAME}"

    cd "${PROJECT_ROOT}"

    # Get user ID and group ID for non-root container
    USER_ID=$(id -u)
    GROUP_ID=$(id -g)

    # Build with buildkit for better performance
    DOCKER_BUILDKIT=1 docker build ${no_cache_flag} \
        --build-arg USER_UID="${USER_ID}" \
        --build-arg USER_GID="${GROUP_ID}" \
        -t "${IMAGE_NAME}" \
        -f "${DOCKERFILE}" \
        .

    if [ $? -eq 0 ]; then
        print_info "Build successful!"
    else
        print_error "Build failed!"
        exit 1
    fi
}

run_container() {
    local outputs_dir="${OUTPUTS_DIR:-${PROJECT_ROOT}/outputs}"
    print_info "Running container: ${CONTAINER_NAME}"

    # Remove existing container if it exists
    if [ "$(docker ps -aq -f name=${CONTAINER_NAME})" ]; then
        print_info "Removing existing container..."
        docker rm -f ${CONTAINER_NAME} > /dev/null
    fi

    # Create necessary directories
    mkdir -p "${outputs_dir}"

    # Use interactive TTY only when stdin is a terminal
    local tty_flags=""
    local name_flags="--name ${CONTAINER_NAME}"
    if [ -t 0 ]; then
        tty_flags="-it"
    else
        name_flags=""
    fi

    # Run with GPU support and volume mount
    docker run ${tty_flags} \
        --rm \
        --gpus all \
        --shm-size 16g \
        ${name_flags} \
        -v "${outputs_dir}:/home/appuser/ViPE/vipe_results" \
        -w /home/appuser/ViPE \
        "${IMAGE_NAME}" \
        "$@"
}

# Main CLI
case "$1" in
    "build")
        shift
        build_image "$@"
        ;;
    "run")
        shift
        run_container "$@"
        ;;
    *)
        if [ -z "$1" ]; then
            # If no argument provided, check if image exists
            if [[ "$(docker images -q ${IMAGE_NAME} 2> /dev/null)" == "" ]]; then
                print_info "Image not found. Building first..."
                build_image
            fi
            run_container
        else
            print_info "Usage: $0 {build|run [command]}"
            print_info "Examples:"
            print_info "  $0 build              # Build the Docker image"
            print_info "  $0 build --clean      # Build from scratch (no cache)"
            print_info "  $0 run                # Run an interactive shell"
            print_info "  $0 run python run.py  # Run a specific command"
        fi
        ;;
esac
