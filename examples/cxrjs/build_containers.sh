#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e  # Exit on error

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT/examples/cxrjs" || exit 1

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
CLEAN=false
IMAGE_PREFIX="cloudxr-teleop"
IMAGE_TAG="latest"

# Print usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --clean         Clean previous build artifacts (node_modules, etc.)"
    echo "  --tag TAG       Docker image tag (default: latest)"
    echo "  -h, --help      Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 --clean --name my-app --tag v1.0"
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --clean)
            CLEAN=true
            shift
            ;;
        --tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            usage
            ;;
    esac
done

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Building CloudXR Web Client PID${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Step 1: Extract the CloudXR Web Client PID
cd "$GIT_ROOT/examples/cxrjs/pid" || exit 1
echo -e "${YELLOW}[1/4] Extracting CloudXR Web Client PID...${NC}"
tar -xzf cloudxr-js-client-6.0.0-beta.tar.gz
echo -e "${GREEN}✓ CloudXR Web Client PID extracted${NC}"
echo ""

# Step 2: Clean up if requested
cd "$GIT_ROOT/examples/cxrjs/pid/isaac" || exit 1
if [ "$CLEAN" = true ]; then
    echo -e "${YELLOW}[2/4] Cleaning previous build artifacts...${NC}"
    rm -rf node_modules
    rm -rf build
    rm -rf .webpack-cache
    echo -e "${GREEN}✓ Cleanup complete${NC}"
    echo ""
else
    echo -e "${YELLOW}[2/4] Skipping cleanup (use --clean to clean previous builds)${NC}"
    echo ""
fi

# Step 3: Install dependencies
echo -e "${YELLOW}[2/4] Installing npm dependencies...${NC}"
npm install ../nvidia-cloudxr-6.0.0-beta.tgz
npm install
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Step 4: Build the web application
echo -e "${YELLOW}[3/4] Building application...${NC}"
npm run build
echo -e "${GREEN}✓ Application built successfully${NC}"
echo ""


echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Building CloudXR Isaac Teleop Container${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
cd "$GIT_ROOT/examples/cxrjs" || exit 1

# Step 1: Build Docker container
echo -e "${YELLOW}[1/2] Building Docker container...${NC}"
docker build \
    --build-arg EXAMPLE_PATH=./pid/isaac/build \
    -t "${IMAGE_PREFIX}-web-app:${IMAGE_TAG}" \
    -f Dockerfile.web-app \
    .
echo -e "${GREEN}✓ Web application container built successfully${NC}"
echo ""

# Step 2: Build the WSS proxy
echo -e "${YELLOW}[2/2] Building WSS proxy...${NC}"
docker build \
    -t "${IMAGE_PREFIX}-wss-proxy:${IMAGE_TAG}" \
    -f Dockerfile.wss-proxy \
    .
echo -e "${GREEN}✓ WSS proxy container built successfully${NC}"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Build Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Docker image: ${GREEN}${IMAGE_PREFIX}-web-app:${IMAGE_TAG}${NC}"
echo -e "Docker image: ${GREEN}${IMAGE_PREFIX}-wss-proxy:${IMAGE_TAG}${NC}"
echo ""
echo "To run the container:"
echo -e "  ${YELLOW}docker run -p 80:80 -p 443:443 ${IMAGE_PREFIX}-web-app:${IMAGE_TAG}${NC}"
echo ""
echo "Then access the application at:"
echo "  HTTP:  http://localhost"
echo "  HTTPS: https://localhost"
echo ""

