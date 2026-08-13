#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Developer helper for people changing Isaac Teleop — not for end users.
#
# When you edit the tree and re-run an install-tree example, uv often keeps a
# cached isaacteleop==X.Y+local wheel, so you silently exercise yesterday's
# build. This script always rebuilds, installs, force-reinstalls that package
# into the example venv, then runs the script so you get the right bits.
#
# End users should follow the docs / released wheels, not this script.
#
# Usage:
#   ./scripts/run_example.sh <example_dir> <script.py> [script args...]
#
# <example_dir> may be under install/ or examples/ (the latter is mapped to
# install/examples/... so uv uses the installed pyproject + find-links wheels).
#
# Examples:
#   ./scripts/run_example.sh examples/retargeting/python \
#       example_retargeters.py --accept-eula
#   ./scripts/run_example.sh examples/deviceio_live_view/python \
#       live_deviceio.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build}"

usage() {
    cat <<'EOF' >&2
Developer helper for people changing Isaac Teleop — not for end users.

When you edit the tree and re-run an install-tree example, uv often keeps a
cached isaacteleop==X.Y+local wheel, so you silently exercise yesterday's
build. This script always rebuilds, installs, force-reinstalls that package
into the example venv, then runs the script so you get the right bits.

End users should follow the docs / released wheels, not this script.

Usage:
  ./scripts/run_example.sh <example_dir> <script.py> [script args...]

<example_dir> may be under install/ or examples/ (the latter is mapped to
install/examples/... so uv uses the installed pyproject + find-links wheels).

Examples:
  ./scripts/run_example.sh install/examples/latency_probe/python \
      latency_probe_example.py --accept-eula
  ./scripts/run_example.sh examples/latency_probe/python \
      latency_probe_example.py --no-launch-cloudxr-runtime
EOF
    exit "${1:-0}"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage 0
fi
if [[ $# -lt 2 ]]; then
    usage 1
fi

EXAMPLE_ARG="$1"
SCRIPT_NAME="$2"
shift 2

if [[ "${EXAMPLE_ARG}" != /* ]]; then
    EXAMPLE_ARG="${REPO_ROOT}/${EXAMPLE_ARG}"
fi
# Canonicalize only when the path already exists (source-tree or prior install).
# install/examples/... may be absent until cmake --install below.
if [[ -d "${EXAMPLE_ARG}" ]]; then
    EXAMPLE_ARG="$(cd "${EXAMPLE_ARG}" && pwd)"
fi

# Prefer the install-tree copy so find-links points at install/wheels.
if [[ "${EXAMPLE_ARG}" == "${REPO_ROOT}/examples/"* ]]; then
    REL_FROM_EXAMPLES="${EXAMPLE_ARG#"${REPO_ROOT}/examples/"}"
    EXAMPLE_DIR="${REPO_ROOT}/install/examples/${REL_FROM_EXAMPLES}"
elif [[ "${EXAMPLE_ARG}" == "${REPO_ROOT}/install/examples/"* ]]; then
    EXAMPLE_DIR="${EXAMPLE_ARG}"
else
    EXAMPLE_DIR="${EXAMPLE_ARG}"
fi

if [[ ! -d "${BUILD_DIR}" ]]; then
    echo "error: build dir not found: ${BUILD_DIR}" >&2
    echo "Configure first, e.g. cmake -B build ..." >&2
    exit 1
fi

cd "${REPO_ROOT}"

echo "==> cmake --build ${BUILD_DIR}"
cmake --build "${BUILD_DIR}"

echo "==> cmake --install ${BUILD_DIR}"
cmake --install "${BUILD_DIR}"

EXAMPLE_DIR="$(cd "${EXAMPLE_DIR}" && pwd)"

if [[ ! -f "${EXAMPLE_DIR}/pyproject.toml" ]]; then
    echo "error: no pyproject.toml in example dir: ${EXAMPLE_DIR}" >&2
    exit 1
fi
if [[ ! -f "${EXAMPLE_DIR}/${SCRIPT_NAME}" ]]; then
    echo "error: script not found: ${EXAMPLE_DIR}/${SCRIPT_NAME}" >&2
    exit 1
fi

echo "==> uv sync --reinstall-package isaacteleop (${EXAMPLE_DIR})"
uv sync --directory "${EXAMPLE_DIR}" --reinstall-package isaacteleop

echo "==> uv run ${SCRIPT_NAME} $*"
exec uv run --directory "${EXAMPLE_DIR}" "${SCRIPT_NAME}" "$@"
