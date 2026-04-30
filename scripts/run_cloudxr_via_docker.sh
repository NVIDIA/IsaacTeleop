#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

# ============================================================================
# DEPRECATION WARNING
# ============================================================================
RED=$'\033[1;31m'
YELLOW=$'\033[1;33m'
CYAN=$'\033[1;36m'
RESET=$'\033[0m'

cat <<EOF >&2

${RED}################################################################################
#                                                                              #
#                          ##  DEPRECATION WARNING  ##                         #
#                                                                              #
################################################################################${RESET}

${YELLOW}This script (run_cloudxr_via_docker.sh) is DEPRECATED and will be REMOVED
in a future release.${RESET}

  Tracking issue:
    ${CYAN}https://github.com/NVIDIA/IsaacTeleop/issues/362${RESET}

If you rely on this script, please comment on the issue above with your
use case and feedback so we can provide you with a smooth migration path.

${RED}################################################################################${RESET}

EOF

# Require interactive acknowledgment before continuing.
if [ -t 0 ]; then
    printf "${YELLOW}Press any key to acknowledge and continue, or Ctrl-C to abort...${RESET}\n"
    read -r -n 1 -s
    printf "\n"
fi
# ============================================================================

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

# Source shared CloudXR environment setup
source scripts/setup_cloudxr_env.sh

# Check CloudXR EULA acceptance
./scripts/check_cloudxr_eula.sh || exit 1

# Download CloudXR Runtime SDK if not already present
./scripts/download_cloudxr_runtime_sdk.sh || exit 1

# Download CloudXR Web SDK if not already present
./scripts/download_cloudxr_sdk.sh || exit 1

# Detect available compose command: "docker compose" (v2) or "docker-compose" (v1)
if docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Run the docker compose file (--build so Dockerfile.web-app / context changes are picked up)
# Note: variables in deps/cloudxr/.env.default are overridden by those in deps/cloudxr/.env
# if a variable exists in both.
$COMPOSE_CMD \
    --env-file "$ENV_DEFAULT" \
    --env-file "$ENV_LOCAL" \
    -f deps/cloudxr/docker-compose.yaml \
    up --build
