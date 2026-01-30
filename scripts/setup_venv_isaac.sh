#!/usr/bin/env bash
set -euo pipefail

# Recreate the local `venv_isaac` Python environment from a pinned requirements file.
#
# Usage:
#   ./scripts/setup_venv_isaac.sh
#
# Notes:
# - We intentionally do NOT commit/copy the `venv_isaac/` directory itself (it is machine-specific).
# - This script recreates it and installs the same Python deps listed in `requirements-venv_isaac.txt`.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${REPO_ROOT}/venv_isaac"
REQ_FILE="${REPO_ROOT}/requirements-venv_isaac.txt"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv not found. Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [[ ! -f "${REQ_FILE}" ]]; then
  echo "Error: ${REQ_FILE} not found." >&2
  exit 1
fi

echo "[INFO] Creating venv: ${VENV_DIR}"
uv venv --python 3.11.14 "${VENV_DIR}"

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "[INFO] Installing pinned requirements from: ${REQ_FILE}"
uv pip install -r "${REQ_FILE}"

echo "[INFO] Done. Activate with:"
echo "  source ${VENV_DIR}/bin/activate"


