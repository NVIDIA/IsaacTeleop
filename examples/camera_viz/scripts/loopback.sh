#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# loopback.sh — run camera_streamer + camera_viz back-to-back on the
# same host for development. Sender ships RTP to 127.0.0.1; receiver
# listens on the matching ports. Same YAML drives both; we just toggle
# ``source: rtp`` for the receiver's copy.
#
# Two modes:
#   1) If a venv is already activated (``$VIRTUAL_ENV`` set), use its
#      Python directly. Recommended — run ``scripts/setup_dev_env.sh``
#      once, ``source .venv/bin/activate``, then just call this script.
#   2) Otherwise fall back to ``uv run --with`` chains (slower, ephemeral
#      env per invocation). Pass ``--with PKG`` for camera-specific deps.
#
# Usage:
#   examples/camera_viz/scripts/loopback.sh <config.yaml> \
#       [--wheel PATH] [--with PKG]...

set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: $0 <config.yaml> [--wheel PATH] [--with PKG]...

Runs camera_streamer + camera_viz on localhost using the same YAML.
With an activated venv, --wheel / --with are ignored.
EOF
    exit 1
}

[[ $# -lt 1 ]] && usage

CONFIG=$1
shift

REPO_ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
CAMERA_VIZ_DIR=$(cd "$(dirname "$0")/.." && pwd)

WHEEL=
EXTRA_WITH=()
while (( $# )); do
    case $1 in
        --wheel) WHEEL=$2; shift 2;;
        --with)  EXTRA_WITH+=("--with" "$2"); shift 2;;
        *) echo "unknown arg: $1" >&2; usage;;
    esac
done

[[ -f "$CONFIG" ]] || { echo "loopback.sh: config $CONFIG not found" >&2; exit 1; }

# Build the python-invocation prefix once. With a venv, it's literally just
# the venv's python. Without, we route through ``uv run --with``.
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    PY_CMD=("$VIRTUAL_ENV/bin/python")
    echo "loopback.sh: using activated venv $VIRTUAL_ENV" >&2
else
    if [[ -z "$WHEEL" ]]; then
        WHEEL=$(ls -1 "$REPO_ROOT"/build/wheels/isaacteleop-*.whl 2>/dev/null | head -1 || true)
    fi
    [[ -n "$WHEEL" && -f "$WHEEL" ]] || {
        echo "loopback.sh: no venv active and no wheel found." >&2
        echo "  Either run scripts/setup_dev_env.sh and activate the venv," >&2
        echo "  or pass --wheel <path>." >&2
        exit 1
    }
    # Default --with set covers V4L2; OAK-D / ZED users add their own.
    if [[ ${#EXTRA_WITH[@]} -eq 0 ]]; then
        EXTRA_WITH=(--with opencv-python)
    fi
    PY_CMD=(
        uv run --python 3.12
        --with "$WHEEL"
        --with cupy-cuda12x
        --with pyyaml
        --with scipy
        "${EXTRA_WITH[@]}"
        python
    )
    echo "loopback.sh: ephemeral uv env (wheel: $(basename "$WHEEL"))" >&2
fi

# Receiver gets a temp copy of the YAML with source: rtp. CLI override
# would work too, but munging the YAML keeps camera_viz.py free of
# loopback-specific knobs.
RECV_CONFIG=$(mktemp --suffix=.yaml)
sed -E 's/^(source:[[:space:]]*).*/\1rtp/' "$CONFIG" > "$RECV_CONFIG"
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

echo "loopback.sh: starting camera_streamer → 127.0.0.1 (background)" >&2
"${PY_CMD[@]}" "$CAMERA_VIZ_DIR/camera_streamer.py" "$CONFIG" --host 127.0.0.1 &
SENDER_PID=$!

# Brief settle so the sender's GStreamer pipeline binds + first IDR is in
# flight before the receiver opens its UDP socket.
sleep 1

echo "loopback.sh: starting camera_viz (foreground) — Ctrl-C to exit" >&2
"${PY_CMD[@]}" "$CAMERA_VIZ_DIR/camera_viz.py" "$RECV_CONFIG"
