#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

export CXR_HOST_VOLUME_PATH=$HOME/.cloudxr
export CXR_UID=$(id -u)
export CXR_GID=$(id -g)

echo "CXR_UID: $CXR_UID"
echo "CXR_GID: $CXR_GID"
echo "CXR_HOST_VOLUME_PATH: $CXR_HOST_VOLUME_PATH"

# Make sure the host volume path exists
mkdir -p $CXR_HOST_VOLUME_PATH

if [ ! -f deps/cloudxr/.env ]; then
    echo "deps/cloudxr/.env not found, creating from scratch..."
    touch deps/cloudxr/.env
fi

# Check CloudXR EULA acceptance
./scripts/check_cloudxr_eula.sh || exit 1

# Run the docker compose file
# Note: When specifying multiple --env-file options to docker compose, variables in later files 
# override earlier ones. Here, variables in deps/cloudxr/.env.default are overridden by those in 
# deps/cloudxr/.env if a variable exists in both.
docker compose \
    --env-file deps/cloudxr/.env.default \
    --env-file deps/cloudxr/.env \
    -f deps/cloudxr/docker-compose.yaml up
