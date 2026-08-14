#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Downloads the CloudXR Web Client SDK if not already present using NGC.
# The SDK is extracted to deps/cloudxr/cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}/ for use by Dockerfile.web-app.
#
# Two ways to obtain the SDK:
# 1) Local tarball: place cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}.tar.gz in deps/cloudxr/.
#    The tarball must extract to the same layout as the NGC release: root must contain
#    nvidia-cloudxr-${CXR_WEB_SDK_VERSION}.tgz (optionally inside a single top-level directory).
# 2) Public NGC: RC versions use nvidia/cloudxr-js-prerelease directly. Other versions
#    try nvidia/cloudxr-js first and fall back to nvidia/cloudxr-js-prerelease.

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

if [[ -z "${CXR_WEB_SDK_VERSION:-}" ]]; then
    echo -e "${RED}Error: CXR_WEB_SDK_VERSION is not set${NC}"
    exit 1
fi

# SDK configuration (shared)
CXR_DEPLOYMENT_DIR="$GIT_ROOT/deps/cloudxr"
SDK_FILE="nvidia-cloudxr-${CXR_WEB_SDK_VERSION}.tgz"
SDK_DIR="cloudxr-js_v${CXR_WEB_SDK_VERSION}"
SDK_RELEASE_DIR="$CXR_DEPLOYMENT_DIR/$SDK_DIR"

is_valid_sdk_bundle() {
    local dir="$1"
    [[ -f "$dir/$SDK_FILE" ]]
}

# Returns 0 if the given directory has valid SDK layout (nvidia-cloudxr-*.tgz)
#
# Only the .tgz is consumed by Dockerfile.web-app; IsaacTeleop builds its web client from
# webxr_client/ in this repo. Earlier bundles also shipped an isaac/ directory, which is no
# longer part of the release, so requiring it here would reject otherwise valid tarballs.
# Kept in sync with is_valid_sdk_bundle(), which the NGC paths use.
is_valid_sdk_layout() {
    local dir="$1"
    [[ -f "$dir/$SDK_FILE" ]]
}

# -----------------------------------------------------------------------------
# Local tarball: path and install logic
# Place cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}.tar.gz in deps/cloudxr/
# -----------------------------------------------------------------------------
install_from_local_tarball() {
    local SDK_TARBALL="$GIT_ROOT/deps/cloudxr/cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}.tar.gz"

    if [[ ! -f "$SDK_TARBALL" ]]; then
        return 1
    fi

    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Installing CloudXR Web SDK from local tarball${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "${YELLOW}Extracting $SDK_TARBALL ...${NC}"
    mkdir -p "$SDK_RELEASE_DIR"
    tar -xzf "$SDK_TARBALL" -C "$SDK_RELEASE_DIR"

    if ! is_valid_sdk_layout "$SDK_RELEASE_DIR"; then
        echo -e "${RED}Error: Tarball layout invalid. Root must contain $SDK_FILE${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ CloudXR Web SDK installed from local tarball${NC}"
    return 0
}

# -----------------------------------------------------------------------------
# Public NGC is anonymous. RC versions go directly to the unlisted prerelease resource;
# non-RC versions try listed first and fall back to unlisted without credentials.
# -----------------------------------------------------------------------------
install_from_public_ngc() {
    local resource="$1"
    local visibility="$2"
    local NGC_URL="https://api.ngc.nvidia.com/v2/resources/org/nvidia/${resource}/${CXR_WEB_SDK_VERSION}/files?redirect=true&path=${SDK_FILE}"

    if ! command -v curl &> /dev/null; then
        echo -e "${RED}Error: curl not found. Please install it first.${NC}"
        echo -e "To use a local SDK instead, place $SDK_FILE in deps/cloudxr/"
        return 1
    fi

    echo -e "${GREEN}==================================${NC}"
    echo -e "${GREEN}Downloading CloudXR Web Client SDK${NC}"
    echo -e "${GREEN}==================================${NC}"
    echo ""

    mkdir -p "$CXR_DEPLOYMENT_DIR"

    echo -e "${YELLOW}Downloading CloudXR Web SDK from ${visibility} NGC resource...${NC}"
    if ! curl --fail --location \
        --connect-timeout 10 --max-time 120 \
        --retry 3 --retry-delay 5 \
        --output "$CXR_DEPLOYMENT_DIR/$SDK_FILE" \
        "$NGC_URL"; then
        echo -e "${RED}Error: Failed to download CloudXR Web SDK from NGC${NC}"
        rm -f "$CXR_DEPLOYMENT_DIR/$SDK_FILE"
        return 1
    fi

    echo -e "${GREEN}✓ CloudXR Web SDK installed successfully${NC}"
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# Check if SDK is already downloaded and extracted
if ([[ -d "$SDK_RELEASE_DIR" ]] && is_valid_sdk_layout "$SDK_RELEASE_DIR") || \
    (is_valid_sdk_bundle "$CXR_DEPLOYMENT_DIR"); then
    echo -e "${GREEN}CloudXR Web SDK already present, skipping download${NC}"
    exit 0
fi

# Error out if the target directory already exists
if [[ -d "$SDK_RELEASE_DIR" ]]; then
    echo -e "${RED}Error downloading CloudXR Web SDK:${NC}"
    echo -e "${RED}  Target directory $SDK_RELEASE_DIR already exists,${NC}"
    echo -e "${RED}  but does not contain the expected files.${NC}"
    echo -e "${RED}  Please remove the directory and try again.${NC}"
    exit 1
fi

# Prefer local tarball if present; otherwise use NGC
if install_from_local_tarball; then
    exit 0
fi

if [[ "$CXR_WEB_SDK_VERSION" == *-rc* ]]; then
    NGC_RESOURCE="cloudxr-js-prerelease"
    NGC_VISIBILITY="unlisted"
else
    NGC_RESOURCE="cloudxr-js"
    NGC_VISIBILITY="listed"
fi

echo "Cannot install from local tarball, trying ${NGC_VISIBILITY} public NGC..."
if install_from_public_ngc "$NGC_RESOURCE" "$NGC_VISIBILITY"; then
    exit 0
fi

if [[ "$NGC_VISIBILITY" == "listed" ]]; then
    NGC_RESOURCE="cloudxr-js-prerelease"
    NGC_VISIBILITY="unlisted"
    echo "Cannot install from listed public NGC, trying unlisted public NGC..."
    if install_from_public_ngc "$NGC_RESOURCE" "$NGC_VISIBILITY"; then
        exit 0
    fi
fi

echo "Cannot install from ${NGC_VISIBILITY} public NGC, exiting..."
exit 1
