#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Camera Streamer — build, run, and manage the camera streaming container.
# Supports arm64 (Jetson Thor / Orin) and x86_64 (Ubuntu).
#
# Two-step build: base Docker image first, then C++ operators compiled inside
# a container with --runtime nvidia (NVENC/NVDEC require GPU driver at build
# time) and committed as the final image.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_NAME="isaac-teleop-camera"
CONTAINER_NAME="isaac-teleop-camera"
DEFAULT_CONFIG="config/multi_camera.yaml"
DEFAULT_RECEIVER_HOST="127.0.0.1"

# CloudXR runtime paths (set by setup_cloudxr_env.sh or defaults)
CXR_HOST_VOLUME_PATH="${CXR_HOST_VOLUME_PATH:-$HOME/.cloudxr}"
XR_RUNTIME_JSON="${XR_RUNTIME_JSON:-$CXR_HOST_VOLUME_PATH/openxr_cloudxr.json}"
NV_CXR_RUNTIME_DIR="${NV_CXR_RUNTIME_DIR:-$CXR_HOST_VOLUME_PATH/run}"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_BOLD="\033[1m"
_DIM="\033[2m"
_GREEN="\033[32m"
_CYAN="\033[36m"
_YELLOW="\033[33m"
_RED="\033[31m"
_RESET="\033[0m"

log_info()  { echo -e "${_CYAN}[info]${_RESET}  $*"; }
log_ok()    { echo -e "${_GREEN}[ok]${_RESET}    $*"; }
log_warn()  { echo -e "${_YELLOW}[warn]${_RESET}  $*" >&2; }
log_error() { echo -e "${_RED}[error]${_RESET} $*" >&2; }
log_step()  { echo -e "\n${_BOLD}=== $* ===${_RESET}"; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

image_tag() {
    echo "$IMAGE_NAME:latest"
}

ensure_image() {
    local tag
    tag="$(image_tag)"
    if ! docker image inspect "$tag" >/dev/null 2>&1; then
        log_warn "Image $tag not found, building..."
        cmd_build
    fi
}

is_inside_container() {
    [[ -f /.dockerenv ]] || grep -qsm1 'docker\|containerd' /proc/1/cgroup 2>/dev/null
}

# Common docker run arguments shared by shell, run, and deploy-sender.
common_docker_args() {
    echo \
        --runtime nvidia \
        --privileged \
        --network=host \
        --ulimit stack=33554432 \
        -e XR_RUNTIME_JSON="$XR_RUNTIME_JSON" \
        -e NV_CXR_RUNTIME_DIR="$NV_CXR_RUNTIME_DIR" \
        -v /dev:/dev \
        -v /run/udev:/run/udev:rw \
        -v "$CXR_HOST_VOLUME_PATH:$CXR_HOST_VOLUME_PATH:ro"
}

show_help() {
    echo -e "${_BOLD}Usage:${_RESET} camera_streamer.sh <command> [options]

${_BOLD}COMMANDS${_RESET}
    build [--sender-only]   Build Docker image (encoder + decoder + XR by default)
                            Inside a container: rebuilds C++ operators only
    shell                   Interactive dev shell (host source mounted)
    run [-- ARGS...]        Run teleop_camera_app.py with the given arguments
    deploy-sender           Deploy the RTP sender as a persistent container
    list-cameras            List connected OAK-D and ZED cameras
    status                  Show whether the container is running
    logs                    Follow container logs
    stop                    Stop the container
    restart                 Restart the container
    clean                   Remove Docker images

${_BOLD}OPTIONS${_RESET}
    --sender-only           Build only the encoder (skip decoder + XR)
    --receiver-host IP      Stream destination IP       (default: $DEFAULT_RECEIVER_HOST)
    --config PATH           Camera config YAML          (default: $DEFAULT_CONFIG)

${_BOLD}MODES${_RESET}
    ${_CYAN}shell${_RESET}           Dev shell. Mounts host camera_streamer/ into the container
                     so Python/config edits are reflected immediately. Built C++
                     libs are at build/python/ on the host.

    ${_CYAN}run${_RESET}             Runs teleop_camera_app.py inside a container with host
                     source mounted. All arguments after -- are forwarded.

    ${_CYAN}deploy-sender${_RESET}   Production mode. Runs teleop_camera_sender.py with
                     --restart unless-stopped. Config file is bind-mounted so
                     you can edit it and restart without rebuilding.

${_BOLD}EXAMPLES${_RESET}
    ./camera_streamer.sh build
    ./camera_streamer.sh shell
    ./camera_streamer.sh run -- --source local --mode monitor
    ./camera_streamer.sh run -- --source rtp --mode xr
    ./camera_streamer.sh deploy-sender --receiver-host 192.168.1.100
    ./camera_streamer.sh status
    ./camera_streamer.sh logs
    ./camera_streamer.sh restart"
}

# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

cmd_build() {
    local SENDER_ONLY=false
    while [[ $# -gt 0 ]]; do
        case $1 in
            --sender-only) SENDER_ONLY=true; shift ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    local BUILD_ENCODER=ON
    local BUILD_DECODER=ON
    if [[ "$SENDER_ONLY" == true ]]; then
        BUILD_DECODER=OFF
        log_info "Building sender only (encoder, no decoder)"
    else
        log_info "Building all operators (encoder + decoder + XR)"
    fi

    if is_inside_container; then
        cmd_build_inplace "$BUILD_ENCODER" "$BUILD_DECODER"
    else
        cmd_build_docker "$BUILD_ENCODER" "$BUILD_DECODER"
    fi
}

cmd_build_inplace() {
    local BUILD_ENCODER="$1"
    local BUILD_DECODER="$2"

    log_step "Rebuilding C++ operators (in-container)"

    local BUILD_DIR="$SCRIPT_DIR/build"
    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"

    cmake "$SCRIPT_DIR" -GNinja -Wno-dev \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DBUILD_ENCODER="$BUILD_ENCODER" \
        -DBUILD_DECODER="$BUILD_DECODER" \
        -DPYTHON_LIB_OUTPUT_DIR="$BUILD_DIR/python"
    ninja

    log_ok "Build complete: ${_DIM}$BUILD_DIR/python${_RESET}"
}

cmd_build_docker() {
    local BUILD_ENCODER="$1"
    local BUILD_DECODER="$2"

    local TAG BASE_TAG BUILD_CONTAINER
    TAG="$(image_tag)"
    BASE_TAG="${IMAGE_NAME}:base"
    BUILD_CONTAINER="${CONTAINER_NAME}-build"

    log_step "Step 1/2: Building base image"
    cd "$SCRIPT_DIR"
    DOCKER_BUILDKIT=1 docker build \
        --progress=auto \
        -f Dockerfile \
        -t "$BASE_TAG" \
        .

    local HOST_BUILD_DIR="$SCRIPT_DIR/build"
    mkdir -p "$HOST_BUILD_DIR"

    log_step "Step 2/2: Compiling C++ operators"
    log_info "Build cache: ${_DIM}$HOST_BUILD_DIR${_RESET}"
    docker rm "$BUILD_CONTAINER" 2>/dev/null || true
    docker run --runtime nvidia --name "$BUILD_CONTAINER" \
        --user "$(id -u):$(id -g)" \
        -v "$HOST_BUILD_DIR:/camera_streamer/build" \
        "$BASE_TAG" \
        bash -c "
            set -e
            cd /camera_streamer/build
            cmake /camera_streamer -GNinja -Wno-dev \
                -DCMAKE_BUILD_TYPE=Release \
                -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
                -DBUILD_ENCODER=$BUILD_ENCODER \
                -DBUILD_DECODER=$BUILD_DECODER \
                -DPYTHON_LIB_OUTPUT_DIR=/camera_streamer/build/python
            ninja
            # build/ is a host mount — not captured by docker commit.
            # Copy Python libs to a non-mounted path for the committed image.
            cp -a /camera_streamer/build/python /camera_streamer/python"

    docker commit "$BUILD_CONTAINER" "$TAG"
    docker rm "$BUILD_CONTAINER"
    docker rmi "$BASE_TAG" 2>/dev/null || true

    echo ""
    log_ok "Image ready: ${_BOLD}$TAG${_RESET}"
    docker images "$TAG" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}"
}

# ---------------------------------------------------------------------------
# shell (interactive dev shell)
# ---------------------------------------------------------------------------

cmd_shell() {
    if docker ps -q --filter "name=$CONTAINER_NAME" --filter "status=running" | grep -q .; then
        log_info "Attaching to running container ${_BOLD}$CONTAINER_NAME${_RESET}"
        exec docker exec -it "$CONTAINER_NAME" /bin/bash
    fi

    log_info "Starting dev shell ${_BOLD}$CONTAINER_NAME${_RESET}"
    log_info "Host source mounted at /camera_streamer"

    ensure_image
    local TAG
    TAG="$(image_tag)"

    exec docker run --rm -it \
        --name "$CONTAINER_NAME" \
        $(common_docker_args) \
        -e DISPLAY="${DISPLAY:-:0}" \
        -v /tmp/.X11-unix:/tmp/.X11-unix \
        -v "$SCRIPT_DIR:/camera_streamer" \
        "$TAG" \
        /bin/bash
}

# ---------------------------------------------------------------------------
# run (run teleop_camera_app.py with forwarded args)
# ---------------------------------------------------------------------------

cmd_run() {
    ensure_image
    local TAG
    TAG="$(image_tag)"

    log_info "Running teleop_camera_app.py $*"

    docker run --rm -it \
        --name "${CONTAINER_NAME}-run" \
        $(common_docker_args) \
        -e DISPLAY="${DISPLAY:-:0}" \
        -v /tmp/.X11-unix:/tmp/.X11-unix \
        -v "$SCRIPT_DIR:/camera_streamer" \
        "$TAG" \
        python3 /camera_streamer/teleop_camera_app.py "$@"
}

# ---------------------------------------------------------------------------
# deploy-sender (production mode)
# ---------------------------------------------------------------------------

SENDER_CONTAINER_NAME="${CONTAINER_NAME}-sender"

cmd_deploy_sender() {
    local RECEIVER_HOST="$DEFAULT_RECEIVER_HOST"
    local CONFIG="$DEFAULT_CONFIG"

    while [[ $# -gt 0 ]]; do
        case $1 in
            --receiver-host) RECEIVER_HOST="$2"; shift 2 ;;
            --config)        CONFIG="$2"; shift 2 ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done

    ensure_image
    local TAG
    TAG="$(image_tag)"

    local HOST_CONFIG="$SCRIPT_DIR/$CONFIG"
    if [[ ! -f "$HOST_CONFIG" ]]; then
        log_error "Config not found: $HOST_CONFIG"
        exit 1
    fi

    local CONFIG_BASENAME
    CONFIG_BASENAME="$(basename "$CONFIG")"

    log_info "Deploying sender ${_BOLD}$SENDER_CONTAINER_NAME${_RESET}"
    log_info "  Image:    $TAG"
    log_info "  Receiver: $RECEIVER_HOST"
    log_info "  Config:   ${_DIM}$HOST_CONFIG${_RESET} (mounted)"

    docker stop "$SENDER_CONTAINER_NAME" 2>/dev/null || true
    docker rm "$SENDER_CONTAINER_NAME" 2>/dev/null || true

    docker run -d \
        --name "$SENDER_CONTAINER_NAME" \
        --restart unless-stopped \
        $(common_docker_args) \
        -v "$HOST_CONFIG:/config/$CONFIG_BASENAME:ro" \
        "$TAG" \
        python3 /camera_streamer/teleop_camera_sender.py \
            --config "/config/$CONFIG_BASENAME" \
            --host "$RECEIVER_HOST"

    echo ""
    docker ps --filter "name=$SENDER_CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}"
    log_ok "Deployed. Edit config and run: ${_BOLD}$0 restart${_RESET}"
}

# ---------------------------------------------------------------------------
# list-cameras
# ---------------------------------------------------------------------------

cmd_list_cameras() {
    # Prefer exec into an already-running container to avoid disruption.
    local running
    running="$(docker ps -q --filter "name=$CONTAINER_NAME" --filter "status=running" | head -1)"
    if [[ -n "$running" ]]; then
        log_info "Listing cameras via running container"
        docker exec "$running" python3 /camera_streamer/list_cameras.py
        return
    fi

    ensure_image
    local TAG
    TAG="$(image_tag)"

    docker run --rm --runtime nvidia --privileged \
        -v /dev:/dev \
        "$TAG" \
        python3 /camera_streamer/list_cameras.py
}

# ---------------------------------------------------------------------------
# Container management
# ---------------------------------------------------------------------------

# Find the first running container whose name starts with $CONTAINER_NAME
# (covers both the dev container and the sender container).
_find_container() {
    docker ps -a --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | head -1
}

cmd_status() {
    local containers
    containers="$(docker ps -a --filter "name=$CONTAINER_NAME" \
        --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}")"
    if [[ -z "$containers" ]]; then
        log_info "No camera streamer containers running"
    else
        echo "$containers"
    fi
}

cmd_logs() {
    local name
    name="$(_find_container)"
    if [[ -z "$name" ]]; then
        log_error "No camera streamer container found"
        exit 1
    fi
    log_info "Following logs for ${_BOLD}$name${_RESET} (Ctrl+C to stop)"
    docker logs -f "$name"
}

cmd_stop() {
    local name
    name="$(_find_container)"
    if [[ -z "$name" ]]; then
        log_error "No camera streamer container found"
        exit 1
    fi
    docker stop "$name"
    log_ok "Container ${_BOLD}$name${_RESET} stopped"
}

cmd_restart() {
    local name
    name="$(_find_container)"
    if [[ -z "$name" ]]; then
        log_error "No camera streamer container found"
        exit 1
    fi
    docker restart "$name"
    log_ok "Container ${_BOLD}$name${_RESET} restarted"
}

cmd_clean() {
    log_info "Removing $IMAGE_NAME images..."
    docker rmi "$(image_tag)" 2>/dev/null || true
    docker rmi "${IMAGE_NAME}:base" 2>/dev/null || true
    docker rm "${CONTAINER_NAME}-build" 2>/dev/null || true
    log_ok "Cleaned"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

[[ $# -eq 0 ]] && { show_help; exit 0; }
CMD="$1"; shift

case "$CMD" in
    build)          cmd_build "$@" ;;
    shell)          cmd_shell ;;
    run)            cmd_run "$@" ;;
    deploy-sender)  cmd_deploy_sender "$@" ;;
    list-cameras)   cmd_list_cameras ;;
    status)         cmd_status ;;
    logs)           cmd_logs ;;
    stop)           cmd_stop ;;
    restart)        cmd_restart ;;
    clean)          cmd_clean ;;
    -h|--help|help) show_help ;;
    *) log_error "Unknown command: $CMD"; show_help; exit 1 ;;
esac
