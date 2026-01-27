#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Test Runner Script with CloudXR
# Runs TeleopCore tests using docker-compose with CloudXR runtime
#
# Usage:
#   ./scripts/run_tests_with_cloudxr.sh [--build]
#
# Options:
#   --build    Force rebuild of test container (no cache)
#   --help     Show this help message

set -e

#==============================================================================
# Configuration - Edit this list to add/remove tests
#==============================================================================
TEST_SCRIPTS=(
    "test_extensions.py"
    "test_modular.py"
)
#==============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Make sure to run this script from the root of the repository
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$GIT_ROOT" || exit 1

# Default values
FORCE_BUILD=false
EXIT_CODE=0

# Compose files and project name
COMPOSE_BASE="deps/cloudxr/docker-compose.yaml"
COMPOSE_TEST="deps/cloudxr/docker-compose.test.yaml"
# Use a different project name to isolate volumes from run_cloudxr.sh
COMPOSE_PROJECT="teleopcore-test"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            FORCE_BUILD=true
            shift
            ;;
        --help)
            echo "Test Runner Script with CloudXR"
            echo ""
            echo "Usage: $0 [--build]"
            echo ""
            echo "Options:"
            echo "  --build    Force rebuild of test container (no cache)"
            echo "  --help     Show this help message"
            echo ""
            echo "Tests to run (edit TEST_SCRIPTS in this script to modify):"
            for test in "${TEST_SCRIPTS[@]}"; do
                echo "  - $test"
            done
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Cleanup function - ensures containers are stopped
cleanup() {
    log_info "Cleaning up containers..."
    docker compose \
        -p "$COMPOSE_PROJECT" \
        --env-file "$ENV_DEFAULT" \
        ${ENV_LOCAL:+--env-file "$ENV_LOCAL"} \
        -f "$COMPOSE_BASE" \
        -f "$COMPOSE_TEST" \
        down -v --remove-orphans 2>/dev/null || true
    log_success "Cleanup complete"
}

# Set up trap to ensure cleanup on exit
trap cleanup EXIT

# Print banner
echo ""
echo -e "${BLUE}=========================================="
echo "  TeleopCore Test Runner with CloudXR"
echo -e "==========================================${NC}"
echo ""

# Check prerequisites
log_info "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    log_error "Docker Compose is not installed"
    exit 1
fi

# Check if we have GPU support
if docker info 2>/dev/null | grep -q "Runtimes.*nvidia"; then
    log_success "NVIDIA Docker runtime detected"
else
    log_warning "NVIDIA Docker runtime not detected - GPU tests may fail"
fi

# Set up environment
log_info "Setting up environment..."

# Source shared CloudXR environment setup
source scripts/setup_cloudxr_env.sh

log_info "TEST_SCRIPTS:"
for test in "${TEST_SCRIPTS[@]}"; do
    log_info "  - $test"
done

# Join array into comma-separated string for docker-compose environment variable
TEST_SCRIPTS_ENV=$(IFS=','; echo "${TEST_SCRIPTS[*]}")
export TEST_SCRIPTS="$TEST_SCRIPTS_ENV"

# In CI, auto-accept EULA
if [ "${CI:-false}" = "true" ]; then
    log_info "CI environment detected, auto-accepting CloudXR EULA"
    echo "ACCEPT_CLOUDXR_EULA=Y" > "$ENV_LOCAL"
fi

# Verify install directory exists and has required artifacts
log_info "Verifying build artifacts..."

if [ ! -d "install/wheels" ]; then
    log_error "install/wheels not found. Please build first:"
    echo "  cmake -B build"
    echo "  cmake --build build --parallel"
    echo "  cmake --install build"
    exit 1
fi

WHEEL_COUNT=$(find install/wheels -name "teleopcore-*.whl" | wc -l)
if [ "$WHEEL_COUNT" -eq 0 ]; then
    log_error "No teleopcore wheel found in install/wheels/"
    exit 1
elif [ "$WHEEL_COUNT" -gt 1 ]; then
    log_error "Multiple teleopcore wheels found - consider cleaning install/wheels/"
    ls -la install/wheels/teleopcore-*.whl
    exit 1
fi

log_success "Found teleopcore wheel in install/wheels/"

# Build test container
log_info "Building test container..."

BUILD_ARGS="-q"
if [ "$FORCE_BUILD" = true ]; then
    BUILD_ARGS="$BUILD_ARGS --no-cache"
fi

docker build \
    $BUILD_ARGS \
    -t teleopcore-tests:latest \
    -f deps/cloudxr/Dockerfile.test \
    .

log_success "Test container built successfully"

# Start CloudXR runtime services
log_info "Starting CloudXR runtime services..."

docker compose \
    -p "$COMPOSE_PROJECT" \
    --env-file "$ENV_DEFAULT" \
    ${ENV_LOCAL:+--env-file "$ENV_LOCAL"} \
    -f "$COMPOSE_BASE" \
    -f "$COMPOSE_TEST" \
    up -d cloudxr-runtime

# Wait for CloudXR runtime to be healthy
log_info "Waiting for CloudXR runtime to be healthy..."

MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if docker compose \
        -p "$COMPOSE_PROJECT" \
        --env-file "$ENV_DEFAULT" \
        ${ENV_LOCAL:+--env-file "$ENV_LOCAL"} \
        -f "$COMPOSE_BASE" \
        -f "$COMPOSE_TEST" \
        ps cloudxr-runtime 2>/dev/null | grep -q "healthy"; then
        log_success "CloudXR runtime is healthy"
        break
    fi

    sleep 2
    WAITED=$((WAITED + 2))
    echo -n "."
done
echo ""

if [ $WAITED -ge $MAX_WAIT ]; then
    log_error "CloudXR runtime failed to become healthy within ${MAX_WAIT}s"
    log_info "Container logs:"
    docker compose \
        -p "$COMPOSE_PROJECT" \
        --env-file "$ENV_DEFAULT" \
        ${ENV_LOCAL:+--env-file "$ENV_LOCAL"} \
        -f "$COMPOSE_BASE" \
        -f "$COMPOSE_TEST" \
        logs cloudxr-runtime
    exit 1
fi

# Run tests
log_info "Running tests..."
echo ""

if docker compose \
    -p "$COMPOSE_PROJECT" \
    --env-file "$ENV_DEFAULT" \
    ${ENV_LOCAL:+--env-file "$ENV_LOCAL"} \
    -f "$COMPOSE_BASE" \
    -f "$COMPOSE_TEST" \
    run --rm teleopcore-tests; then
    log_success "All tests passed!"
    EXIT_CODE=0
else
    log_error "Some tests failed"
    EXIT_CODE=1
fi

# Output test results for CI
if [ "${CI:-false}" = "true" ]; then
    echo ""
    echo "::group::Container Logs"
    docker compose \
        -p "$COMPOSE_PROJECT" \
        --env-file "$ENV_DEFAULT" \
        ${ENV_LOCAL:+--env-file "$ENV_LOCAL"} \
        -f "$COMPOSE_BASE" \
        -f "$COMPOSE_TEST" \
        logs
    echo "::endgroup::"
fi

echo ""
echo -e "${BLUE}=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}  ✅ Tests Completed Successfully${NC}"
else
    echo -e "${RED}  ❌ Tests Failed${NC}"
fi
echo -e "${BLUE}==========================================${NC}"
echo ""

exit $EXIT_CODE
