#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Run CloudXR runtime (via installed wheel) and the WSS proxy together.
# The proxy runs in the background; the runtime runs in the foreground.
# Ctrl+C / SIGTERM tears both down.
#
# Requires isaacteleop[cloudxr] to be installed before running this script.

set -euo pipefail

GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

source scripts/setup_cloudxr_env.sh

PROXY_PID=""

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
    echo "Error: isaacteleop[cloudxr] is not installed. Install it before running this script (e.g. pip install isaacteleop[cloudxr])."
    echo "Follow the Quick Start guide to install the package via pypi: https://nvidia.github.io/IsaacTeleop/main/getting_started/quick_start.html"
    echo "Or build and install the package from source: https://nvidia.github.io/IsaacTeleop/main/getting_started/build_from_source.html"
    exit 1
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
