#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Downloads the CloudXR Runtime SDK if not already present using NGC.
# The SDK tarball (CloudXR-<VERSION>-Linux-<ARCH>-sdk.tar.gz) is placed in deps/cloudxr/
# for use by Dockerfile.runtime.
#
# Three ways to obtain the SDK (tried in order):
# 1) Local tarball: place CloudXR-<VERSION>-Linux-<ARCH>-sdk.tar.gz in deps/cloudxr/.
# 2) Public NGC: downloads via curl from the public NGC resource API.
# 3) Private NGC: downloads via curl from the private NGC resource API; requires NGC_API_KEY.
# Optional: set CXR_DOWNLOAD_EXP=1 to also download CloudXR-exp-<VERSION>-....

set -Eeuo pipefail

on_error() {
    local exit_code="$?"
    local line_no="$1"
    echo "Error: ${BASH_SOURCE[0]} failed at line ${line_no} (exit ${exit_code})" >&2
    exit "$exit_code"
}

trap 'on_error $LINENO' ERR

# Ensure we're in the git root
if [[ -z "${GIT_ROOT:-}" ]]; then
    GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
    if [[ -z "$GIT_ROOT" ]]; then
        echo "Error: Could not determine git root. Set GIT_ROOT before sourcing." >&2
        exit 1
    fi
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

if [[ -z "${CXR_RUNTIME_SDK_VERSION:-}" ]]; then
    echo -e "${RED}Error: CXR_RUNTIME_SDK_VERSION is not set${NC}"
    exit 1
fi

# SDK configuration (shared)
CXR_DEPLOYMENT_DIR="$GIT_ROOT/deps/cloudxr"

case "$(uname -m)" in
    x86_64)        ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) echo -e "${RED}Error: Unsupported architecture '$(uname -m)'.${NC}"; exit 1 ;;
esac

SDK_FILE="CloudXR-${CXR_RUNTIME_SDK_VERSION}-Linux-${ARCH}-sdk.tar.gz"
EXP_SDK_FILE="CloudXR-exp-${CXR_RUNTIME_SDK_VERSION}-Linux-${ARCH}-sdk.tar.gz"

is_valid_sdk_bundle() {
    local dir="$1"
    [[ -f "$dir/$SDK_FILE" ]] || return 1
    if [[ "${CXR_DOWNLOAD_EXP:-0}" == "1" ]]; then
        [[ -f "$dir/$EXP_SDK_FILE" ]] || return 1
    fi
    return 0
}

# -----------------------------------------------------------------------------
# Local tarball: place $SDK_FILE in deps/cloudxr/
# -----------------------------------------------------------------------------
install_from_local_tarball() {
    if ! is_valid_sdk_bundle "$CXR_DEPLOYMENT_DIR"; then
        return 1
    fi
    echo -e "${GREEN}✓ CloudXR Runtime SDK found at $CXR_DEPLOYMENT_DIR/$SDK_FILE${NC}"
    if [[ "${CXR_DOWNLOAD_EXP:-0}" == "1" ]]; then
        echo -e "${GREEN}✓ CloudXR Experimental Runtime SDK found at $CXR_DEPLOYMENT_DIR/$EXP_SDK_FILE${NC}"
    fi
    return 0
}

# -----------------------------------------------------------------------------
# NGC download helper
# -----------------------------------------------------------------------------
download_ngc_file() {
    local url="$1"
    local out_path="$2"
    local label="$3"
    local auth_bearer="${4:-}"

    [[ -s "$out_path" ]] && return 0

    echo -e "${YELLOW}Downloading ${label}...${NC}"
    local -a curl_args=(--fail --location --output "$out_path")
    if [[ -n "$auth_bearer" ]]; then
        curl_args+=(-H "Authorization: Bearer ${auth_bearer}" -H "Content-Type: application/json")
    fi
    if ! curl "${curl_args[@]}" "$url"; then
        echo -e "${RED}Error: Failed to download ${label}${NC}"
        rm -f "$out_path"
        return 1
    fi
    if [[ ! -s "$out_path" ]]; then
        echo -e "${RED}Error: Downloaded ${label} is empty${NC}"
        rm -f "$out_path"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Public NGC: download via curl from the public NGC resource API
# Resource: nvidia/cloudxr-runtime-for-isaac-teleop/${CXR_RUNTIME_SDK_VERSION}
# -----------------------------------------------------------------------------
install_from_public_ngc() {
    if ! command -v curl &> /dev/null; then
        echo -e "${RED}Error: curl not found. Please install it first.${NC}"
        echo -e "To use a local SDK instead, place $SDK_FILE in deps/cloudxr/"
        return 1
    fi

    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Downloading CloudXR Runtime SDK${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""

    mkdir -p "$CXR_DEPLOYMENT_DIR"

    local base="https://api.ngc.nvidia.com/v2/resources/org/nvidia/cloudxr-runtime-for-isaac-teleop/${CXR_RUNTIME_SDK_VERSION}/files?redirect=true&path="
    download_ngc_file \
        "${base}${SDK_FILE}" \
        "$CXR_DEPLOYMENT_DIR/$SDK_FILE" \
        "CloudXR Runtime SDK" || return 1
    if [[ "${CXR_DOWNLOAD_EXP:-0}" == "1" ]]; then
        download_ngc_file \
            "${base}${EXP_SDK_FILE}" \
            "$CXR_DEPLOYMENT_DIR/$EXP_SDK_FILE" \
            "CloudXR Experimental Runtime SDK" || return 1
    fi

    echo -e "${GREEN}✓ CloudXR Runtime SDK installed successfully${NC}"
    echo ""
}

# -----------------------------------------------------------------------------
# Private NGC: download via curl from the private NGC resource API
# Resource: 0566138804516934/cloudxr-dev/cloudxr-runtime-binary:${VERSION}-public
# Requires NGC_API_KEY for Bearer-token auth.
# Optional: CXR_RUNTIME_NGC_SUFFIX is appended to CXR_RUNTIME_SDK_VERSION (default: -public).
# -----------------------------------------------------------------------------
install_from_private_ngc() {
    local NGC_ORG="0566138804516934"
    local NGC_TEAM="cloudxr-dev"
    local NGC_RESOURCE="cloudxr-runtime-binary"
    local NGC_VERSION="${CXR_RUNTIME_SDK_VERSION}${CXR_RUNTIME_NGC_SUFFIX:--public}"
    local NGC_SDK_FILE="CloudXR-external-${CXR_RUNTIME_SDK_VERSION}-Linux-${ARCH}-sdk.tar.gz"
    local NGC_EXP_SDK_FILE="CloudXR-exp-external-${CXR_RUNTIME_SDK_VERSION}-Linux-${ARCH}-sdk.tar.gz"
    local base="https://api.ngc.nvidia.com/v2/org/${NGC_ORG}/team/${NGC_TEAM}/resources/${NGC_RESOURCE}/versions/${NGC_VERSION}/files"

    if [[ -z "${NGC_API_KEY:-}" ]]; then
        echo -e "${RED}Error: NGC_API_KEY is not set; cannot download from private NGC${NC}"
        return 1
    fi

    if ! command -v curl &> /dev/null; then
        echo -e "${RED}Error: curl not found. Please install it first.${NC}"
        return 1
    fi

    echo -e "${GREEN}=================================================${NC}"
    echo -e "${GREEN}Downloading CloudXR Runtime SDK from private NGC${NC}"
    echo -e "${GREEN}=================================================${NC}"
    echo ""

    mkdir -p "$CXR_DEPLOYMENT_DIR"

    download_ngc_file \
        "${base}/${NGC_SDK_FILE}" \
        "$CXR_DEPLOYMENT_DIR/$SDK_FILE" \
        "CloudXR Runtime SDK" \
        "$NGC_API_KEY" || return 1
    if [[ "${CXR_DOWNLOAD_EXP:-0}" == "1" ]]; then
        download_ngc_file \
            "${base}/${NGC_EXP_SDK_FILE}" \
            "$CXR_DEPLOYMENT_DIR/$EXP_SDK_FILE" \
            "CloudXR Experimental Runtime SDK" \
            "$NGC_API_KEY" || return 1
    fi

    echo -e "${GREEN}✓ CloudXR Runtime SDK installed successfully${NC}"
    echo ""
    return 0
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# Prefer local tarball if present; otherwise use NGC
if install_from_local_tarball; then
    exit 0
fi

echo "Cannot install from local tarball, trying public NGC..."
if install_from_public_ngc; then
    exit 0
fi

echo "Cannot install from public NGC, trying private NGC..."
if install_from_private_ngc; then
    exit 0
fi

echo "Cannot install from private NGC, exiting..."
exit 1
