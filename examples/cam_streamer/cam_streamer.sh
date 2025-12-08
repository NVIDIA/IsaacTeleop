#!/bin/bash
# OAK-D Camera Streamer - Build, Deploy & Receive

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults
DEFAULT_IP="192.168.123.164"
DEFAULT_USER="unitree"
DEFAULT_STREAM_HOST="192.168.123.222"
IMAGE_NAME="oakd-streamer"
CONTAINER_NAME="oakd-cam-streamer"

show_help() {
    cat << 'EOF'
Usage: cam_streamer.sh <command> [options]

COMMANDS:
    deploy [--ip IP] [--user USER] [--stream-host IP]
        Build robot image, deploy to Jetson, run sender with auto-restart

    receive [--port PORT] [--hw]
        Build host receiver image and run locally

    send [--stream-host IP] [--stream-port PORT]
        Build host sender image and run locally (for testing)

    log/stop/restart [--ip IP] [--user USER]
        Manage remote container

    clean
        Remove all oakd-streamer Docker images

DEFAULTS:
    Robot: unitree@192.168.123.164, Stream to: 192.168.123.222:5000
EOF
}

cmd_deploy() {
    local IP="$DEFAULT_IP" USER="$DEFAULT_USER" STREAM_HOST="$DEFAULT_STREAM_HOST"
    while [[ $# -gt 0 ]]; do
        case $1 in
            --ip) IP="$2"; shift 2 ;; --user) USER="$2"; shift 2 ;;
            --stream-host) STREAM_HOST="$2"; shift 2 ;; *) echo "Unknown: $1"; exit 1 ;;
        esac
    done

    local TAG="$IMAGE_NAME:robot"
    echo "Building $TAG..."
    cd "$SCRIPT_DIR"
    DOCKER_BUILDKIT=1 docker build --platform linux/arm64 -f Dockerfile.robot -t "$TAG" .

    echo "Deploying to $USER@$IP..."
    local TARBALL="/tmp/oakd-robot.tar.gz"
    docker save "$TAG" | gzip > "$TARBALL"
    scp "$TARBALL" "$USER@$IP:/tmp/"

    ssh "$USER@$IP" bash << EOF
sudo docker load < /tmp/oakd-robot.tar.gz && rm /tmp/oakd-robot.tar.gz
sudo docker stop $CONTAINER_NAME 2>/dev/null || true
sudo docker rm $CONTAINER_NAME 2>/dev/null || true
sudo docker run -d --name $CONTAINER_NAME --restart unless-stopped \
    --privileged --network=host -v /dev:/dev -v /run/udev:/run/udev:rw \
    $TAG python3 gstreamer_oakd_sender.py --stream-host $STREAM_HOST
EOF
    rm "$TARBALL"
    echo "Deployed. Use: $0 log | stop | restart"
}

cmd_receive() {
    local PORT=5000 HW_FLAG=""
    while [[ $# -gt 0 ]]; do
        case $1 in
            --port) PORT="$2"; shift 2 ;; --hw) HW_FLAG="--hw"; shift ;;
            *) echo "Unknown: $1"; exit 1 ;;
        esac
    done

    local TAG="$IMAGE_NAME:host"
    if ! docker image inspect "$TAG" >/dev/null 2>&1; then
        echo "Building $TAG..."
        cd "$SCRIPT_DIR"
        docker build -f Dockerfile.host -t "$TAG" .
    fi

    echo "Starting receiver on port $PORT..."
    docker run --rm -it --network=host \
        -e DISPLAY="$DISPLAY" -v /tmp/.X11-unix:/tmp/.X11-unix \
        "$TAG" python3 gstreamer_oakd_receiver.py --port "$PORT" $HW_FLAG
}

cmd_send() {
    local STREAM_HOST="127.0.0.1" STREAM_PORT=5000
    while [[ $# -gt 0 ]]; do
        case $1 in
            --stream-host) STREAM_HOST="$2"; shift 2 ;; --stream-port) STREAM_PORT="$2"; shift 2 ;;
            *) echo "Unknown: $1"; exit 1 ;;
        esac
    done

    local TAG="$IMAGE_NAME:host-sender"
    if ! docker image inspect "$TAG" >/dev/null 2>&1; then
        echo "Building $TAG..."
        cd "$SCRIPT_DIR"
        docker build -f Dockerfile.robot -t "$TAG" .
    fi

    echo "Starting sender, streaming to $STREAM_HOST:$STREAM_PORT..."
    docker run --rm -it --privileged --network=host \
        -v /dev:/dev -v /run/udev:/run/udev:rw \
        "$TAG" python3 gstreamer_oakd_sender.py --stream-host "$STREAM_HOST" --stream-port "$STREAM_PORT"
}

parse_remote_args() {
    IP="$DEFAULT_IP"
    USER="$DEFAULT_USER"
    while [[ $# -gt 0 ]]; do
        case $1 in
            --ip) IP="$2"; shift 2 ;;
            --user) USER="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
}

cmd_log() {
    parse_remote_args "$@"
    ssh -t "$USER@$IP" "sudo docker logs -f $CONTAINER_NAME"
}

cmd_stop() {
    parse_remote_args "$@"
    ssh "$USER@$IP" "sudo docker stop $CONTAINER_NAME" && echo "Stopped"
}

cmd_restart() {
    parse_remote_args "$@"
    ssh "$USER@$IP" "sudo docker restart $CONTAINER_NAME" && echo "Restarted"
}

cmd_clean() {
    echo "Removing oakd-streamer images..."
    docker rmi "$IMAGE_NAME:host" "$IMAGE_NAME:host-sender" "$IMAGE_NAME:robot" 2>/dev/null || true
    echo "Cleaned"
}

[[ $# -eq 0 ]] && { show_help; exit 0; }
CMD="$1"; shift
case "$CMD" in
    deploy)  cmd_deploy "$@" ;;
    send)    cmd_send "$@" ;;
    receive) cmd_receive "$@" ;;
    log)     cmd_log "$@" ;;
    stop)    cmd_stop "$@" ;;
    restart) cmd_restart "$@" ;;
    clean)   cmd_clean ;;
    -h|--help|help) show_help ;;
    *) echo "Unknown: $CMD"; show_help; exit 1 ;;
esac
