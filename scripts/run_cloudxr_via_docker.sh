#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

USE_LOCAL_WHEELS=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --use-local-wheels)
            USE_LOCAL_WHEELS=1
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--use-local-wheels]"
            echo "  --use-local-wheels  Install isaacteleop from install/wheels inside Docker."
            exit 0
            ;;
        *)
            echo "Error: Unknown argument: $1"
            echo "Usage: $0 [--use-local-wheels]"
            exit 1
            ;;
    esac
done

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

# Source shared CloudXR environment setup
source scripts/setup_cloudxr_env.sh

# Check CloudXR EULA acceptance
./scripts/check_cloudxr_eula.sh || exit 1

# Download CloudXR Web SDK if not already present
./scripts/download_cloudxr_sdk.sh || exit 1

if [ "$USE_LOCAL_WHEELS" -eq 1 ]; then
    # Verify install directory exists and has required artifacts
    if [ ! -d "install/wheels" ]; then
        echo "Error: install/wheels not found. Please build first:"
        echo "  cmake -B build"
        echo "  cmake --build build --parallel"
        echo "  cmake --install build"
        exit 1
    fi

    WHEEL_COUNT=$(find install/wheels -name "isaacteleop-*.whl" | wc -l)
    if [ "$WHEEL_COUNT" -eq 0 ]; then
        echo "Error: No isaacteleop wheel found in install/wheels/"
        exit 1
    fi

    echo "Found $WHEEL_COUNT isaacteleop wheel(s) in install/wheels/"
fi

# Compose interpolation reads environment variables from the shell.
export PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
export CXR_BUILD_CONTEXT="$GIT_ROOT"

export ISAACTELEOP_PIP_SPEC="isaacteleop[cloudxr]~=1.0.0"
if [ "$USE_LOCAL_WHEELS" -eq 1 ]; then
    # Make docker-compose.runtime install from a local wheel directory via pip find-links.
    export ISAACTELEOP_PIP_FIND_LINKS="/workspace/install/wheels"
else
    unset ISAACTELEOP_PIP_FIND_LINKS
fi
export ISAACTELEOP_PIP_DEBUG=0

# Detect available compose command: "docker compose" (v2) or "docker-compose" (v1)
if docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Run the docker compose file (--build so Dockerfile.web-app / context changes are picked up)
# Note: variables in deps/cloudxr/.env.default are overridden by those in deps/cloudxr/.env
# if a variable exists in both.
$COMPOSE_CMD \
    --env-file "$ENV_DEFAULT" \
    --env-file "$ENV_LOCAL" \
    -f deps/cloudxr/docker-compose.runtime.yaml \
    -f deps/cloudxr/docker-compose.web-app.yaml \
    up --build
