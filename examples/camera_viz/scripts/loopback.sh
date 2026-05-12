#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# loopback.sh — run camera_streamer + camera_viz back-to-back on the
# same host for development. Sender ships RTP to 127.0.0.1; receiver
# listens on the matching ports. Same YAML drives both; we just toggle
# ``source: rtp`` for the receiver's copy.
#
# Usage:
#   examples/camera_viz/scripts/loopback.sh examples/camera_viz/configs/v4l2.yaml \
#       [--wheel build/wheels/isaacteleop-*.whl] \
#       [--with EXTRA_PKG ...]
#
# Defaults to a wheel at build/wheels/isaacteleop-*.whl. Add ``--with
# depthai`` (OAK-D) / ``--with opencv-python`` (V4L2) etc. as your
# camera demands.

set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: $0 <config.yaml> [--wheel PATH] [--with PKG]...

Runs camera_streamer + camera_viz on localhost using the same YAML.
EOF
    exit 1
}

[[ $# -lt 1 ]] && usage

CONFIG=$1
shift

REPO_ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
WHEEL=$(ls -1 "$REPO_ROOT"/build/wheels/isaacteleop-*.whl 2>/dev/null | head -1 || true)
EXTRA_WITH=("--with" "opencv-python")  # default: V4L2 path covered

while (( $# )); do
    case $1 in
        --wheel) WHEEL=$2; shift 2;;
        --with)  EXTRA_WITH+=("--with" "$2"); shift 2;;
        *) echo "unknown arg: $1" >&2; usage;;
    esac
done

[[ -n "$WHEEL" && -f "$WHEEL" ]] || {
    echo "loopback.sh: wheel not found — pass --wheel <path> or build it first" >&2
    exit 1
}
[[ -f "$CONFIG" ]] || { echo "loopback.sh: config $CONFIG not found" >&2; exit 1; }

CAMERA_VIZ_DIR=$(cd "$(dirname "$0")/.." && pwd)

# Receiver gets a temp copy of the YAML with source: rtp. We could
# instead pass a CLI override, but munging the YAML keeps camera_viz.py
# free of loopback-specific knobs.
RECV_CONFIG=$(mktemp --suffix=.yaml)
sed -E 's/^(source:[[:space:]]*).*/\1rtp/' "$CONFIG" > "$RECV_CONFIG"
# Sanity: confirm the substitution actually flipped something.
grep -q '^source:[[:space:]]*rtp' "$RECV_CONFIG" || {
    echo "loopback.sh: failed to set source: rtp in temp config" >&2
    cat "$RECV_CONFIG" >&2
    rm -f "$RECV_CONFIG"
    exit 1
}

SENDER_PID=
cleanup() {
    if [[ -n "$SENDER_PID" ]] && kill -0 "$SENDER_PID" 2>/dev/null; then
        echo "loopback.sh: stopping sender (pid $SENDER_PID)" >&2
        kill -TERM "$SENDER_PID" 2>/dev/null || true
        wait "$SENDER_PID" 2>/dev/null || true
    fi
    rm -f "$RECV_CONFIG"
}
trap cleanup EXIT INT TERM

UV_ARGS=(--python 3.12 --with "$WHEEL" --with cupy-cuda12x --with pyyaml --with scipy "${EXTRA_WITH[@]}")

echo "loopback.sh: starting camera_streamer → 127.0.0.1 (background)" >&2
uv run "${UV_ARGS[@]}" \
    python "$CAMERA_VIZ_DIR/camera_streamer.py" "$CONFIG" --host 127.0.0.1 &
SENDER_PID=$!

# Brief settle so the sender's GStreamer pipeline binds + first IDR is
# in flight before the receiver opens its UDP socket.
sleep 1

echo "loopback.sh: starting camera_viz (foreground) — Ctrl-C to exit" >&2
uv run "${UV_ARGS[@]}" \
    python "$CAMERA_VIZ_DIR/camera_viz.py" "$RECV_CONFIG"
