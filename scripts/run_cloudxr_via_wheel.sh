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

find_local_wheel() {
    local wheel_dir
    for wheel_dir in install/wheels build/wheels; do
        if ls "$wheel_dir"/isaacteleop-*.whl >/dev/null 2>&1; then
            ls "$wheel_dir"/isaacteleop-*.whl | sort | tail -n1
            return 0
        fi
    done
    return 1
}

build_and_install_wheel() {
    echo "Building and installing local isaacteleop wheel..."
    if [ ! -f build/CMakeCache.txt ]; then
        cmake -B build
    fi
    cmake --build build --parallel
    cmake --install build
}

cleanup() {
    if [ -n "$PROXY_PID" ] && kill -0 "$PROXY_PID" 2>/dev/null; then
        echo "Stopping WSS proxy (PID $PROXY_PID)..."
        kill "$PROXY_PID" 2>/dev/null
        wait "$PROXY_PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT INT TERM

echo "Starting WSS proxy..."
if ! python -c "import isaacteleop.cloudxr; import isaacteleop.cloudxr.wss" >/dev/null 2>&1; then
    if ! command -v uv &>/dev/null; then
        echo "Error: uv is not on PATH. See the README for installation instructions."
        exit 1
    fi
    WHEEL="$(find_local_wheel || true)"
    if [ -z "$WHEEL" ]; then
        build_and_install_wheel
        WHEEL="$(find_local_wheel || true)"
    fi
    if [ -z "$WHEEL" ]; then
        echo "Error: Could not locate a local isaacteleop wheel after build/install."
        exit 1
    fi
    echo "Bootstrapping isaacteleop from local wheel: $WHEEL"
    WHEEL_URI=$(python -c "import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve().as_uri())" "$WHEEL")
    uv pip install \
        --python "$(command -v python)" \
        --reinstall \
        "isaacteleop[cloudxr] @ $WHEEL_URI"

    if ! python -c "import isaacteleop.cloudxr; import isaacteleop.cloudxr.wss" >/dev/null 2>&1; then
        build_and_install_wheel
        WHEEL="$(find_local_wheel || true)"
        if [ -z "$WHEEL" ]; then
            echo "Error: Could not locate a local isaacteleop wheel after rebuild."
            exit 1
        fi
        WHEEL_URI=$(python -c "import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve().as_uri())" "$WHEEL")
        uv pip install \
            --python "$(command -v python)" \
            --reinstall \
            "isaacteleop[cloudxr] @ $WHEEL_URI"
    fi
fi

python -m isaacteleop.cloudxr.wss &
PROXY_PID=$!
sleep 2
if ! kill -0 "$PROXY_PID" 2>/dev/null; then
    echo "Error: WSS proxy failed to start."
    exit 1
fi

echo "Starting CloudXR runtime..."
python -m isaacteleop.cloudxr
