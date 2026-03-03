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
    local -a wheels=()
    local wheel_dir
    for wheel_dir in install/wheels build/wheels; do
        if [ -d "$wheel_dir" ]; then
            while IFS= read -r -d '' wheel; do
                wheels+=("$wheel")
            done < <(find "$wheel_dir" -maxdepth 1 -type f -name 'isaacteleop-*.whl' -print0)
        fi
    done
    if [ ${#wheels[@]} -eq 0 ]; then
        return 1
    fi
    local latest_basename
    latest_basename=$(printf '%s\n' "${wheels[@]}" | sed 's!.*/!!' | sort -V | tail -n1)
    local wheel
    for wheel in "${wheels[@]}"; do
        if [ "${wheel##*/}" = "$latest_basename" ]; then
            printf '%s\n' "$wheel"
            return 0
        fi
    done
    return 0
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
        echo "Error: isaacteleop.cloudxr import still failing after wheel install."
        echo "Diagnostics:"
        python -c "import sys; print('python:', sys.executable); print('version:', sys.version)" || true
        echo "PYTHONPATH=${PYTHONPATH:-<unset>}"
        uv pip list --python "$(command -v python)" || true
        python -c "import traceback; import isaacteleop.cloudxr; import isaacteleop.cloudxr.wss" 2>&1 || true
        exit 1
    fi
fi

python -m isaacteleop.cloudxr.wss &
PROXY_PID=$!

PROXY_PORT_VALUE="${PROXY_PORT:-48322}"
PROXY_READY=false
for _ in $(seq 1 20); do
    if ! kill -0 "$PROXY_PID" 2>/dev/null; then
        break
    fi
    if bash -c "exec 3<>/dev/tcp/127.0.0.1/${PROXY_PORT_VALUE}" 2>/dev/null; then
        PROXY_READY=true
        break
    fi
    sleep 0.5
done
if [ "$PROXY_READY" = false ]; then
    echo "Error: WSS proxy failed to accept connections on localhost:${PROXY_PORT_VALUE}."
    if kill -0 "$PROXY_PID" 2>/dev/null; then
        kill "$PROXY_PID" 2>/dev/null || true
    fi
    exit 1
fi

echo "Starting CloudXR runtime..."
python -m isaacteleop.cloudxr
