#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

# Source shared CloudXR environment setup
source scripts/setup_cloudxr_env.sh

# Check CloudXR EULA acceptance
./scripts/check_cloudxr_eula.sh || exit 1

# Download CloudXR Web SDK if not already present
./scripts/download_cloudxr_sdk.sh || exit 1

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
    -f deps/cloudxr/docker-compose.yaml \
    up --build
