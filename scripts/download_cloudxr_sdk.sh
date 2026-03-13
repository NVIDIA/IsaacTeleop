#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Downloads the CloudXR Web Client SDK if not already present using NGC.
# The SDK is extracted to deps/cloudxr/cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}/ for use by Dockerfile.web-app.
#
# Three ways to obtain the SDK (tried in order):
# 1) Local tarball: place cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}.tar.gz in deps/cloudxr/.
#    The tarball must extract to the same layout as the NGC release: root must contain
#    isaac/ and nvidia-cloudxr-${CXR_WEB_SDK_VERSION}.tgz (optionally inside a single top-level directory).
# 2) Public NGC: downloads via wget from the public NGC resource API (no NGC CLI needed).
# 3) Private NGC: requires ngc CLI; downloads from private NGC org.

set -Eeuo pipefail

on_error() {
    local exit_code="$?"
    local line_no="$1"
    echo "Error: ${BASH_SOURCE[0]} failed at line ${line_no} (exit ${exit_code})" >&2
    exit "$exit_code"
}

trap 'on_error $LINENO' ERR

# Ensure we're in the git root
if [ -z "${GIT_ROOT:-}" ]; then
    GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
    if [ -z "$GIT_ROOT" ]; then
        echo "Error: Could not determine git root. Set GIT_ROOT before sourcing." >&2
        exit 1
    fi
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

if [ -z "${CXR_WEB_SDK_VERSION:-}" ]; then
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
    [ -f "$dir/$SDK_FILE" ]
}

# Returns 0 if the given directory has valid SDK layout (isaac/ and nvidia-cloudxr-*.tgz)
is_valid_sdk_layout() {
    local dir="$1"
    [ -d "$dir/isaac" ] && [ -f "$dir/$SDK_FILE" ]
}

# -----------------------------------------------------------------------------
# Local tarball: path and install logic
# Place cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}.tar.gz in deps/cloudxr/
# -----------------------------------------------------------------------------
install_from_local_tarball() {
    local SDK_TARBALL="$GIT_ROOT/deps/cloudxr/cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}.tar.gz"

    if [ ! -f "$SDK_TARBALL" ]; then
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
        echo -e "${RED}Error: Tarball layout invalid. Root must contain isaac/ and $SDK_FILE${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ CloudXR Web SDK installed from local tarball${NC}"
    return 0
}

# -----------------------------------------------------------------------------
# Public NGC: download via wget from the public NGC resource API
# Resource: nvidia/cloudxr-js/${CXR_WEB_SDK_VERSION}
# -----------------------------------------------------------------------------
install_from_public_ngc() {
    local NGC_URL="https://api.ngc.nvidia.com/v2/resources/org/nvidia/cloudxr-js/${CXR_WEB_SDK_VERSION}/files?redirect=true&path=${SDK_FILE}"

    if ! command -v wget &> /dev/null; then
        echo -e "${RED}Error: wget not found. Please install it first.${NC}"
        echo -e "To use a local SDK instead, place $SDK_FILE in deps/cloudxr/"
        return 1
    fi

    echo -e "${GREEN}==================================${NC}"
    echo -e "${GREEN}Downloading CloudXR Web Client SDK${NC}"
    echo -e "${GREEN}==================================${NC}"
    echo ""

    mkdir -p "$CXR_DEPLOYMENT_DIR"

    echo -e "${YELLOW}Downloading CloudXR Web SDK from NGC...${NC}"
    if ! wget --content-disposition \
        --output-document "$CXR_DEPLOYMENT_DIR/$SDK_FILE" \
        "$NGC_URL"; then
        echo -e "${RED}Error: Failed to download CloudXR Web SDK from NGC${NC}"
        rm -f "$CXR_DEPLOYMENT_DIR/$SDK_FILE"
        return 1
    fi

    echo -e "${GREEN}✓ CloudXR Web SDK installed successfully${NC}"
    echo ""
}

# -----------------------------------------------------------------------------
# NGC: resource path and download/install logic
# Resource: 0566138804516934/cloudxr-dev/cloudxr-js:${CXR_WEB_SDK_VERSION}
# -----------------------------------------------------------------------------
install_from_private_ngc() {
    local NGC_ORG="0566138804516934"
    local SDK_RESOURCE="${NGC_ORG}/cloudxr-dev/cloudxr-js:${CXR_WEB_SDK_VERSION}"
    local SDK_DOWNLOAD_DIR="$GIT_ROOT/deps/cloudxr/.sdk-download"
    local DOWNLOADED_TAR_BALL="$SDK_DOWNLOAD_DIR/cloudxr-js_v${CXR_WEB_SDK_VERSION}/$SDK_FILE"

    mkdir -p "$SDK_DOWNLOAD_DIR"

    echo -e "${YELLOW}[1/3] Downloading CloudXR Web SDK from NGC...${NC}"
    cd "$SDK_DOWNLOAD_DIR"
    ngc registry resource download-version \
        --org "$NGC_ORG" \
        --team no-team \
        --file "$SDK_FILE" \
        "$SDK_RESOURCE"

    local DOWNLOADED_DIR="$(basename "$(find . -mindepth 1 -maxdepth 1 -type d -name 'cloudxr-js_v*' -print -quit)")"
    if [ -z "$DOWNLOADED_DIR" ]; then
        echo -e "${RED}Error: Failed to find downloaded SDK directory${NC}"
        return 1
    fi

    echo -e "Moving $DOWNLOADED_TAR_BALL to $GIT_ROOT/deps/cloudxr"
    mv "$DOWNLOADED_TAR_BALL" "$GIT_ROOT/deps/cloudxr"

    echo -e "${GREEN}✓ CloudXR Web SDK installed successfully${NC}"
    echo ""
    return 0
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# Check if SDK is already downloaded and extracted
if ([ -d "$SDK_RELEASE_DIR" ] && is_valid_sdk_layout "$SDK_RELEASE_DIR") || \
    (is_valid_sdk_bundle "$CXR_DEPLOYMENT_DIR"); then
    echo -e "${GREEN}CloudXR Web SDK already present, skipping download${NC}"
    exit 0
fi

# Error out if the target directory already exists
if [ -d "$SDK_RELEASE_DIR" ]; then
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
