#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Run CloudXR runtime (via installed wheel) and the WSS proxy together.
# The proxy runs in the background; the runtime runs in the foreground.
# Ctrl+C / SIGTERM tears both down.

set -euo pipefail

GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

source scripts/setup_cloudxr_env.sh

PROXY_PID=""
WHEEL=""

cleanup() {
    if [ -n "$PROXY_PID" ] && kill -0 "$PROXY_PID" 2>/dev/null; then
        echo "Stopping WSS proxy (PID $PROXY_PID)..."
        kill "$PROXY_PID" 2>/dev/null
        wait "$PROXY_PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT INT TERM

if ! command -v uv &>/dev/null; then
    echo "Error: uv is not on PATH. See the README for installation instructions."
    exit 1
fi

echo "Starting WSS proxy..."
uv run --directory deps/cloudxr wss_proxy.py &
PROXY_PID=$!
sleep 2
if ! kill -0 "$PROXY_PID" 2>/dev/null; then
    echo "Error: WSS proxy failed to start."
    exit 1
fi

echo "Starting CloudXR runtime..."
if ! python -c "import isaacteleop.cloudxr" >/dev/null 2>&1; then
    for wheel_dir in install/wheels build/wheels; do
        if ls "$wheel_dir"/isaacteleop-*.whl >/dev/null 2>&1; then
            WHEEL=$(ls "$wheel_dir"/isaacteleop-*.whl | sort | tail -n1)
            break
        fi
    done
    if [ -z "$WHEEL" ]; then
        echo "Error: isaacteleop.cloudxr is not importable and no local wheel was found."
        echo "Build/install first: cmake --build build && cmake --install build"
        exit 1
    fi
    echo "Bootstrapping isaacteleop from local wheel: $WHEEL"
    uv pip install \
        --python "$(command -v python)" \
        --find-links "$(dirname "$WHEEL")" \
        --reinstall \
        --prerelease=allow \
        isaacteleop
fi

python -m isaacteleop.cloudxr
