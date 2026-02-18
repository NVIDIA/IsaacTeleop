# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Shared CloudXR environment setup script
# Sources environment files and ensures required directories exist
#
# Usage: source this script from other scripts
#   source scripts/setup_cloudxr_env.sh
#
# Exports:
#   CXR_UID, CXR_GID - User/group IDs for container
#   ENV_DEFAULT, ENV_LOCAL - Paths to env files
#   CXR_HOST_VOLUME_PATH - Host path for CloudXR volume

# Ensure we're in the git root
if [ -z "$GIT_ROOT" ]; then
    GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
    if [ -z "$GIT_ROOT" ]; then
        echo "Error: Could not determine git root. Set GIT_ROOT before sourcing." >&2
        return 1 2>/dev/null || exit 1
    fi
fi

# Export user/group IDs for container permissions
export CXR_UID=$(id -u)
export CXR_GID=$(id -g)

# Env file paths (relative to GIT_ROOT)
export ENV_DEFAULT="deps/cloudxr/.env.default"
export ENV_LOCAL="deps/cloudxr/.env"

# Create .env file if it doesn't exist
if [ ! -f "$GIT_ROOT/$ENV_LOCAL" ]; then
    echo "deps/cloudxr/.env not found, creating from scratch..."
    touch "$GIT_ROOT/$ENV_LOCAL"
fi

# Source env files to get CXR_HOST_VOLUME_PATH and other variables
# Note: .env overrides .env.default (source order matters)
set -a  # auto-export sourced variables
source "$GIT_ROOT/$ENV_DEFAULT"
source "$GIT_ROOT/$ENV_LOCAL"
set +a

# Make sure the host volume path exists
mkdir -p "$CXR_HOST_VOLUME_PATH"

# Export OpenXR configs
export XR_RUNTIME_JSON="$CXR_HOST_VOLUME_PATH/share/openxr/1/openxr_cloudxr.json"
export NV_CXR_RUNTIME_DIR="$CXR_HOST_VOLUME_PATH/run"

echo "CloudXR has been configured as the OpenXR runtime:"
echo ""
echo "CXR_HOST_VOLUME_PATH: $CXR_HOST_VOLUME_PATH"
echo "XR_RUNTIME_JSON: $XR_RUNTIME_JSON"
echo "NV_CXR_RUNTIME_DIR: $NV_CXR_RUNTIME_DIR"
