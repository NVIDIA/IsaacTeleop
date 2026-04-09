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
#   CXR_ENV_FILE - Path to generated cloudxr.env (source in other terminals)

# This script is intended to be sourced, so it must not change the caller's
# shell strict-mode options (e.g., -e/-u/pipefail).

# Ensure we're in the git root
if [ -z "${GIT_ROOT:-}" ]; then
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
    if ! touch "$GIT_ROOT/$ENV_LOCAL"; then
        echo "Error: Failed to create $GIT_ROOT/$ENV_LOCAL." >&2
        return 1 2>/dev/null || exit 1
    fi
fi

# Source env files to get CXR_HOST_VOLUME_PATH and other variables
# Note: .env overrides .env.default (source order matters)
__CXR_ALLEXPORT_WAS_SET=false
if [[ $- == *a* ]]; then
    __CXR_ALLEXPORT_WAS_SET=true
fi

__cxr_restore_allexport_state() {
    if [ "$__CXR_ALLEXPORT_WAS_SET" = false ]; then
        set +a
    fi
    unset __CXR_ALLEXPORT_WAS_SET
    unset -f __cxr_restore_allexport_state
}

set -a  # auto-export sourced variables
if ! source "$GIT_ROOT/$ENV_DEFAULT"; then
    __cxr_restore_allexport_state
    echo "Error: Failed to source $GIT_ROOT/$ENV_DEFAULT." >&2
    return 1 2>/dev/null || exit 1
fi

if ! source "$GIT_ROOT/$ENV_LOCAL"; then
    __cxr_restore_allexport_state
    echo "Error: Failed to source $GIT_ROOT/$ENV_LOCAL." >&2
    return 1 2>/dev/null || exit 1
fi

__cxr_restore_allexport_state

if [ -z "${CXR_HOST_VOLUME_PATH:-}" ]; then
    echo "Error: CXR_HOST_VOLUME_PATH is not set. Check $GIT_ROOT/$ENV_DEFAULT and $GIT_ROOT/$ENV_LOCAL." >&2
    return 1 2>/dev/null || exit 1
fi

# Make sure the host volume path exists
if ! mkdir -p "$CXR_HOST_VOLUME_PATH"; then
    echo "Error: Failed to create CXR_HOST_VOLUME_PATH at $CXR_HOST_VOLUME_PATH." >&2
    return 1 2>/dev/null || exit 1
fi

# Export OpenXR configs
export XR_RUNTIME_JSON="$CXR_HOST_VOLUME_PATH/openxr_cloudxr.json"
export NV_CXR_RUNTIME_DIR="$CXR_HOST_VOLUME_PATH/run"

# ---------------------------------------------------------------------------
# Write cloudxr.env so other terminals can activate the CloudXR environment.
# Mirrors the env file written by EnvConfig._resolve_and_apply() in the
# native Python path (python -m isaacteleop.cloudxr).
# ---------------------------------------------------------------------------
__cxr_to_bool() {
    case "$1" in
        1|true|True|TRUE) printf true ;;
        0|false|False|FALSE) printf false ;;
        *) printf '%s' "$1" ;;
    esac
}

_CXR_LOGS_DIR="$CXR_HOST_VOLUME_PATH/logs"
mkdir -p "$NV_CXR_RUNTIME_DIR" "$_CXR_LOGS_DIR"

export CXR_ENV_FILE="$NV_CXR_RUNTIME_DIR/cloudxr.env"
cat > "$CXR_ENV_FILE" <<CLOUDXR_ENV
export CXR_HOST_VOLUME_PATH=$CXR_HOST_VOLUME_PATH
export CXR_INSTALL_DIR=$CXR_HOST_VOLUME_PATH
export NV_CXR_ENABLE_PUSH_DEVICES=$(__cxr_to_bool "${NV_CXR_ENABLE_PUSH_DEVICES:-true}")
export NV_CXR_ENABLE_TENSOR_DATA=$(__cxr_to_bool "${NV_CXR_ENABLE_TENSOR_DATA:-true}")
export NV_CXR_FILE_LOGGING=$(__cxr_to_bool "${NV_CXR_FILE_LOGGING:-true}")
export NV_CXR_OUTPUT_DIR=$_CXR_LOGS_DIR
export NV_CXR_RUNTIME_DIR=$NV_CXR_RUNTIME_DIR
export NV_DEVICE_PROFILE=${NV_DEVICE_PROFILE:-auto-webrtc}
export XRT_NO_STDIN=true
export XR_RUNTIME_JSON=$XR_RUNTIME_JSON
CLOUDXR_ENV
chmod 600 "$CXR_ENV_FILE"

unset -f __cxr_to_bool
unset _CXR_LOGS_DIR

echo "CloudXR has been configured as the OpenXR runtime:"
echo ""
echo "CXR_HOST_VOLUME_PATH: $CXR_HOST_VOLUME_PATH"
echo "XR_RUNTIME_JSON: $XR_RUNTIME_JSON"
echo "NV_CXR_RUNTIME_DIR: $NV_CXR_RUNTIME_DIR"
echo ""
echo "Activate CloudXR in another terminal: source $CXR_ENV_FILE"
