#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# In-container mesh generation over Dyn-HaMR world results. Copied into
# /home/appuser/Dyn-HaMR/dyn-hamr/ by docker/Dockerfile.dynhamr. Invoke via
# scripts/run_mesh_generation.sh on the host, not directly on the host.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RESULTS_DIR="${1:-/home/appuser/outputs}"
PHASE="${PHASE:-smooth_fit}"
GPU="${GPU:-0}"
MANO_MODEL_DIR="${MANO_MODEL_DIR:-/home/appuser/Dyn-HaMR/_DATA/data/mano}"
PYTHON="${PYTHON:-python}"

EXTRA_ARGS=""
[ "${NO_TEMPORAL_SMOOTH:-0}" = "1" ] && EXTRA_ARGS="${EXTRA_ARGS} --no_temporal_smooth"
[ "${NO_SMOOTH_TRANS:-0}" = "1" ]    && EXTRA_ARGS="${EXTRA_ARGS} --no_smooth_trans"

if [ ! -d "${RESULTS_DIR}" ]; then
    echo "Error: Directory not found: ${RESULTS_DIR}"
    echo "Usage: $0 [results_dir]"
    exit 1
fi

if [ ! -f "${MANO_MODEL_DIR}/MANO_RIGHT.pkl" ]; then
    echo "Error: MANO_RIGHT.pkl not found in ${MANO_MODEL_DIR}/"
    echo "Run /home/appuser/setup_dynhamr.sh inside the container to populate it"
    echo "(requires MANO_RIGHT.pkl in the mounted outputs/ directory on the host)."
    exit 1
fi

RESULTS_DIR="$(cd "${RESULTS_DIR}" && pwd)"
echo "=========================================="
echo "Hand mesh generation"
echo "=========================================="
echo "Results dir:  ${RESULTS_DIR}"
echo "Phase:        ${PHASE}"
echo "GPU:          ${GPU}"
echo "MANO models:  ${MANO_MODEL_DIR}"
echo ""

mapfile -t LOG_DIRS < <(
  find "${RESULTS_DIR}" -path "*/${PHASE}/*_world_results.npz" -type f 2>/dev/null \
    | while read -r f; do
        ( cd "$(dirname "$f")/.." && pwd )
      done | sort -u
)

if [ ${#LOG_DIRS[@]} -eq 0 ]; then
    echo "No *_world_results.npz under */${PHASE}/ found under ${RESULTS_DIR}. Nothing to do."
    exit 0
fi

echo "Found ${#LOG_DIRS[@]} log dir(s)."
echo ""

SUCCESS=0
SKIP=0
FAIL=0

for LOG_DIR in "${LOG_DIRS[@]}"; do
    PHASE_DIR="${LOG_DIR}/${PHASE}"
    if [ ! -d "${PHASE_DIR}" ]; then
        echo "[SKIP] ${LOG_DIR}  (no ${PHASE}/ subdir)"
        SKIP=$((SKIP + 1))
        continue
    fi

    echo "------------------------------------------"
    echo "Processing: ${LOG_DIR}"
    if "${PYTHON}" "${SCRIPT_DIR}/save_hand_mesh_trajectory.py" \
            --log-dir "${LOG_DIR}" \
            --phase "${PHASE}" \
            --gpu "${GPU}" \
            --mano-model-dir "${MANO_MODEL_DIR}" \
            ${EXTRA_ARGS}; then
        SUCCESS=$((SUCCESS + 1))
    else
        echo "WARNING: save_hand_mesh_trajectory.py failed for ${LOG_DIR}"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "=========================================="
echo "Hand mesh generation done."
echo "=========================================="
echo "  Succeeded: ${SUCCESS}"
echo "  Skipped:   ${SKIP}  (no ${PHASE}/ subdir)"
echo "  Failed:    ${FAIL}"
echo ""
echo "Output .npz files written alongside world_results in each <log_dir>/${PHASE}/."
