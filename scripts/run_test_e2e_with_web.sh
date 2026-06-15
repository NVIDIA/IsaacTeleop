#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Quick-start E2E Test Runner with CloudXR
#
# Brings up the CloudXR runtime + a static HTTP server (serving the prebuilt
# webxr_client) in one container, then:
#   1. Runs Playwright against the web client (browser session live).
#   2. Runs the gripper retargeting example while the runtime is still up,
#      verifying the full Python teleop pipeline end-to-end.
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
#   PYTHON_VERSION             Python version for Dockerfile.runtime / tests (3.11)
#   ISAACTELEOP_PIP_FIND_LINKS pip find-links inside Dockerfile.runtime build
#                              context (/workspace/install/wheels)
#   ISAACTELEOP_PIP_SPEC       isaacteleop pip spec (isaacteleop[cloudxr])
#   ISAACTELEOP_PIP_DEBUG      Verbose pip install output (0)
#   ISAACTELEOP_TESTS_IMAGE    Pre-built test image for gripper-example
#                              (isaacteleop-tests:latest)

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
export ISAACTELEOP_TESTS_IMAGE="${ISAACTELEOP_TESTS_IMAGE:-isaacteleop-tests:latest}"

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

GRIPPER_LOG="${GIT_ROOT}/gripper-example.log"

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

echo "Quick-start E2E project: $PROJECT"
echo "Web app dir:             $CXR_WEBAPP_DIR"
echo ""

# Build the isaacteleop-tests image used by the gripper-example service.
echo "Building isaacteleop-tests image (for gripper-example)..."
docker build \
    -q \
    --build-arg PYTHON_VERSION="$PYTHON_VERSION" \
    -t "$ISAACTELEOP_TESTS_IMAGE" \
    -f deps/cloudxr/Dockerfile.test \
    .

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

# Run Playwright and the gripper example concurrently so the browser WebXR
# session is live while the Python retargeting pipeline runs.
echo "Running Playwright spec and gripper retargeting example concurrently..."

playwright_rc=0
gripper_rc=0

"${COMPOSE[@]}" run --rm playwright &
playwright_pid=$!

"${COMPOSE[@]}" run --rm gripper-example \
    > "$GRIPPER_LOG" 2>&1 &
gripper_pid=$!

# Wait for both and capture exit codes independently.
wait "$playwright_pid" || playwright_rc=$?
wait "$gripper_pid"    || gripper_rc=$?

# Always print the gripper log so CI surfaces output on both pass and fail.
echo "::group::Gripper retargeting example output"
cat "$GRIPPER_LOG" || true
echo "::endgroup::"

if [ "$playwright_rc" -ne 0 ]; then
    echo "Error: Playwright spec failed (exit $playwright_rc)" >&2
    exit "$playwright_rc"
fi

if [ "$gripper_rc" -ne 0 ]; then
    echo "Error: Gripper example exited with code $gripper_rc" >&2
    exit "$gripper_rc"
fi

HEADER_MARKER="Gripper Retargeting - Squeeze triggers to control grippers"
if ! grep -q "$HEADER_MARKER" "$GRIPPER_LOG"; then
    echo "Error: expected header '${HEADER_MARKER}' not found in gripper output" >&2
    exit 1
fi

if ! grep -qE '^\[.*s\] Right:' "$GRIPPER_LOG"; then
    echo "Error: no status output lines found in gripper output" >&2
    exit 1
fi

echo "All quick-start E2E checks passed."
