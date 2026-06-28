#!/usr/bin/env bash
#
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT_DIR=$(git rev-parse --show-toplevel)
ENV_DEFAULT="$ROOT_DIR/deps/cloudxr/.env.default"

SDK_VERSION="${SDK_VERSION:-${CXR_WEB_SDK_VERSION:-}}"
if [[ -z "$SDK_VERSION" ]]; then
    SDK_VERSION=$(grep -E '^CXR_WEB_SDK_VERSION=.+' "$ENV_DEFAULT" | cut -d= -f2)
fi

SDK_TARBALL="$ROOT_DIR/deps/cloudxr/nvidia-cloudxr-${SDK_VERSION}.tgz"
if [[ ! -f "$SDK_TARBALL" ]]; then
    echo "Missing CloudXR Web SDK tarball: $SDK_TARBALL" >&2
    echo "Run scripts/download_cloudxr_sdk.sh before running this container test." >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required to run the web client smoke container test." >&2
    exit 1
fi

PLAYWRIGHT_IMAGE="${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.61.1-noble}"
RUN_SUFFIX="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}-$$"
SAFE_SUFFIX=$(printf '%s' "$RUN_SUFFIX" | tr -c 'A-Za-z0-9_.-' '-')
CONTAINER_NAME="cloudxr-web-smoke-${SAFE_SUFFIX}"
NETWORK_NAME="${CONTAINER_NAME}-net"

cleanup() {
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NETWORK_NAME" >/dev/null

docker run --rm \
    --name "$CONTAINER_NAME" \
    --network "$NETWORK_NAME" \
    -v "$ROOT_DIR:/workspace" \
    -w /workspace/deps/cloudxr/webxr_client \
    -e CI="${CI:-1}" \
    -e SDK_VERSION="$SDK_VERSION" \
    -e CLIENT_GIT_REF="${CLIENT_GIT_REF:-}" \
    -e CLIENT_GIT_SHA="${CLIENT_GIT_SHA:-}" \
    -e PLAYWRIGHT_HOST=0.0.0.0 \
    -e PLAYWRIGHT_PORT=8080 \
    -e PLAYWRIGHT_BASE_URL=http://127.0.0.1:8080 \
    "$PLAYWRIGHT_IMAGE" \
    bash -lc '
        set -euo pipefail
        npm install "../nvidia-cloudxr-${SDK_VERSION}.tgz"
        USE_LOCAL_WEBXR_ASSETS=0 npm run build
        npm test
        npm run test:smoke
    '
