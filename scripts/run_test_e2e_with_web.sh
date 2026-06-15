#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Web E2E Test Runner with CloudXR
#
# Brings up the CloudXR runtime + a static HTTP server (serving the prebuilt
# webxr_client) in one container, then runs Playwright against it from a
# second container, then tears the stack down.
#
# Project-scoped via -p so multiple invocations on the same host (e.g.
# parallel CI matrix jobs) do not collide on container/network/volume names.
#
# Usage:
#   ./scripts/run_test_e2e_with_web.sh
#
# Required environment:
#   CXR_WEBAPP_DIR             Absolute path to the prebuilt webxr_client
#                              build/ directory (bind-mounted into the runtime
#                              container at /app/webapp).
#
# Optional environment (with defaults):
#   PYTHON_VERSION             Python version for Dockerfile.runtime (3.11)
#   ISAACTELEOP_PIP_FIND_LINKS pip find-links inside Dockerfile.runtime build
#                              context (/workspace/install/wheels)
#   ISAACTELEOP_PIP_SPEC       isaacteleop pip spec (isaacteleop[cloudxr])
#   ISAACTELEOP_PIP_DEBUG      Verbose pip install output (0)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$GIT_ROOT"

if [ -z "${CXR_WEBAPP_DIR:-}" ]; then
    echo "Error: CXR_WEBAPP_DIR is required (absolute path to webxr_client build/ output)" >&2
    exit 1
fi

if [ ! -f "$CXR_WEBAPP_DIR/index.html" ]; then
    echo "Error: $CXR_WEBAPP_DIR does not contain index.html — pass the webxr_client build/ directory" >&2
    exit 1
fi

# Project-scope container names, networks, and Docker-managed volumes across
# parallel jobs. -p namespaces every Compose-created resource.
PROJECT="isaacteleop-web-e2e-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$(uname -m)"

# Dockerfile.runtime build args (consumed by the build: section in
# docker-compose.test-e2e.yaml).
export CXR_BUILD_CONTEXT="$GIT_ROOT"
export PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
export ISAACTELEOP_PIP_SPEC="${ISAACTELEOP_PIP_SPEC:-isaacteleop[cloudxr]}"
export ISAACTELEOP_PIP_FIND_LINKS="${ISAACTELEOP_PIP_FIND_LINKS:-/workspace/install/wheels}"
export ISAACTELEOP_PIP_DEBUG="${ISAACTELEOP_PIP_DEBUG:-0}"

# Default-on EULA for non-interactive runs; the compose file already defaults
# this but exporting here keeps `docker compose config` output deterministic.
export ACCEPT_CLOUDXR_EULA="${ACCEPT_CLOUDXR_EULA:-Y}"

# Run the Playwright container as the invoking user so writes through the
# tests/web_e2e bind mount (test-results/, package-lock.json) end up with the
# runner's ownership rather than root's. Without this, GitHub Actions cleanup
# between jobs fails to remove the workspace and re-runs (local or CI) hit
# permission errors on the same paths.
export PLAYWRIGHT_UID="$(id -u)"
export PLAYWRIGHT_GID="$(id -g)"

COMPOSE=(
    docker compose
    -p "$PROJECT"
    -f deps/cloudxr/docker-compose.test-e2e.yaml
)

teardown() {
    local rc=$?
    {
        echo "::group::Compose logs"
        "${COMPOSE[@]}" logs --no-color > "$GIT_ROOT/e2e-logs.txt" 2>&1 || true
        cat "$GIT_ROOT/e2e-logs.txt" || true
        echo "::endgroup::"
        "${COMPOSE[@]}" down -v --remove-orphans 2>/dev/null || true
    } >&2
    exit "$rc"
}
trap teardown EXIT

echo "Web E2E project: $PROJECT"
echo "Web app dir:     $CXR_WEBAPP_DIR"
echo ""

echo "Building and starting cloudxr-runtime..."
"${COMPOSE[@]}" up --build -d cloudxr-runtime

echo "Waiting for cloudxr-runtime to become healthy..."
healthy=false
for _ in $(seq 1 60); do
    status="$("${COMPOSE[@]}" ps cloudxr-runtime --format '{{.Health}}' 2>/dev/null || true)"
    case "$status" in
        *unhealthy*)
            echo "Error: cloudxr-runtime entered unhealthy state" >&2
            "${COMPOSE[@]}" logs cloudxr-runtime || true
            exit 1
            ;;
        *healthy*)
            healthy=true
            break
            ;;
    esac
    sleep 2
done

if [ "$healthy" != true ]; then
    echo "Error: cloudxr-runtime did not become healthy within timeout" >&2
    "${COMPOSE[@]}" logs cloudxr-runtime || true
    exit 1
fi

echo "Running Playwright spec..."
"${COMPOSE[@]}" run --rm playwright
