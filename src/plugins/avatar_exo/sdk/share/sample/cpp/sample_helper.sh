#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# With AVATAR_DIST_PREFIX set (mock deb tree), SDK files are under that package root.
_root="${AVATAR_DIST_PREFIX:-}"
SDK_PREFIX="${_root}/opt/avatar-sdk"
DEFAULT_CONFIG="${SDK_PREFIX}/share/sdk_config.json"
CONFIG_PATH="${1:-${DEFAULT_CONFIG}}"
RUN_SECONDS="${2:-}"
BUILD_DIR="${BUILD_DIR:-$(if [[ -w "${SCRIPT_DIR}" ]]; then printf '%s' build; else printf '%s' "${TMPDIR:-/tmp}/avatar-sdk-sample-cpp"; fi)}"

cd "${SCRIPT_DIR}"

echo "Building C++ example..."
make INCLUDE_DIR="${SDK_PREFIX}/include" LIB_DIR="${SDK_PREFIX}/lib" BUILD_DIR="${BUILD_DIR}"

echo "Running avatar_example with config: ${CONFIG_PATH}"
if [[ -n "${RUN_SECONDS}" ]]; then
  exec "${BUILD_DIR}/avatar_example" "${CONFIG_PATH}" "${RUN_SECONDS}"
fi
exec "${BUILD_DIR}/avatar_example" "${CONFIG_PATH}"
