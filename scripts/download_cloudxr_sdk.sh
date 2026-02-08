#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Downloads the CloudXR Web Client EA SDK if not already present using NGC.
# The SDK is extracted to deps/cloudxr/cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}/ for use by Dockerfile.web-app.
#
# Two ways to obtain the SDK:
# 1) NGC (default): requires ngc CLI; downloads nvidia/cloudxr-js-early-access:${CXR_WEB_SDK_VERSION}.
# 2) Local tarball: place cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}.tar.gz in deps/cloudxr/.
#    The tarball must extract to the same layout as the NGC release: root must contain
#    isaac/ and nvidia-cloudxr-${CXR_WEB_SDK_VERSION}.tgz (optionally inside a single top-level directory).

set -e

# Ensure we're in the git root
if [ -z "$GIT_ROOT" ]; then
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

if [ -z "$CXR_WEB_SDK_VERSION" ]; then
    echo -e "${RED}Error: CXR_WEB_SDK_VERSION is not set${NC}"
    exit 1
fi

# SDK configuration (shared)
SDK_RELEASE_DIR="$GIT_ROOT/deps/cloudxr/cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}"

# Returns 0 if the given directory has valid SDK layout (isaac/ and nvidia-cloudxr-*.tgz)
is_valid_sdk_layout() {
    local dir="$1"
    [ -d "$dir/isaac" ] && [ -f "$dir/nvidia-cloudxr-${CXR_WEB_SDK_VERSION}.tgz" ]
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
        echo -e "${RED}Error: Tarball layout invalid. Root must contain isaac/ and nvidia-cloudxr-${CXR_WEB_SDK_VERSION}.tgz${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ CloudXR Web SDK installed from local tarball${NC}"
    return 0
}

# -----------------------------------------------------------------------------
# NGC: resource path and download/install logic
# Resource: nvidia/cloudxr-js-early-access:${CXR_WEB_SDK_VERSION}
# -----------------------------------------------------------------------------
install_from_ngc() {
    local SDK_RESOURCE="nvidia/cloudxr-js-early-access:${CXR_WEB_SDK_VERSION}"
    local SDK_DOWNLOAD_DIR="$GIT_ROOT/deps/cloudxr/.sdk-download"

    if ! command -v ngc &> /dev/null; then
        echo -e "${RED}Error: NGC CLI not found. Please install it first.${NC}"
        echo -e "To use a local SDK instead, place cloudxr-web-sdk-${CXR_WEB_SDK_VERSION}.tar.gz in deps/cloudxr/"
        echo -e "Visit: https://ngc.nvidia.com/setup/installers/cli"
        exit 1
    fi

    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Downloading CloudXR Web Client EA SDK${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""

    mkdir -p "$SDK_DOWNLOAD_DIR"

    echo -e "${YELLOW}[1/3] Downloading CloudXR Web SDK from NGC...${NC}"
    cd "$SDK_DOWNLOAD_DIR"
    ngc registry resource download-version \
        --team no-team \
        "$SDK_RESOURCE"

    DOWNLOADED_DIR=$(ls -d cloudxr-js-early-access_v* 2>/dev/null | head -n1)
    if [ -z "$DOWNLOADED_DIR" ]; then
        echo -e "${RED}Error: Failed to find downloaded SDK directory${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓ CloudXR Web SDK downloaded${NC}"
    echo ""

    echo -e "${YELLOW}[2/3] Extracting SDK...${NC}"
    cd "$SDK_DOWNLOAD_DIR/$DOWNLOADED_DIR"

    if [ ! -f "release.tar.gz" ]; then
        echo -e "${RED}Error: release.tar.gz not found in downloaded SDK${NC}"
        exit 1
    fi

    SDK_EXTRACT_DIR="$SDK_DOWNLOAD_DIR/extracted"
    mkdir -p "$SDK_EXTRACT_DIR"
    tar -xzf release.tar.gz -C "$SDK_EXTRACT_DIR"
    echo -e "${GREEN}✓ SDK extracted${NC}"
    echo ""

    echo -e "${YELLOW}[3/3] Installing SDK to deps/cloudxr/release/...${NC}"
    rm -rf "$SDK_RELEASE_DIR"
    mv "$SDK_EXTRACT_DIR" "$SDK_RELEASE_DIR"

    echo -e "${GREEN}✓ CloudXR Web SDK installed successfully${NC}"
    echo ""
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# Check if SDK is already downloaded and extracted
if [ -d "$SDK_RELEASE_DIR" ] && is_valid_sdk_layout "$SDK_RELEASE_DIR"; then
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

install_from_ngc
