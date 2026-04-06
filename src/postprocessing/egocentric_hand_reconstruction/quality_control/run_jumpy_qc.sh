#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Run jumpy-hand QC scripts on Dyn-HaMR world_results (after scripts/run_reconstruction.sh).
# Uses host Python; no Docker required. See README_jumpy_qc.md for details.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Default: search under outputs/ for logs/.../video-custom/.../smooth_fit/*_world_results.npz
RESULTS_DIR="${1:-outputs}"
TRANS_FACTOR="${TRANS_FACTOR:-20.0}"
ROT_FACTOR="${ROT_FACTOR:-20.0}"
# FPS: optional second arg, or env FPS (for useful seconds in cal_jumpy_proportions)
FPS="${2:-${FPS:-}}"

if [ ! -d "${RESULTS_DIR}" ]; then
    echo "Error: Directory not found: ${RESULTS_DIR}"
    echo "Usage: $0 [results_dir] [fps]"
    echo "  results_dir  Directory containing Dyn-HaMR logs (default: outputs)"
    echo "  fps          Optional FPS for useful seconds in proportions (e.g. 30)"
    echo ""
    echo "Optional env: TRANS_FACTOR, ROT_FACTOR (default 20.0), FPS (if not passed as second arg)."
    exit 1
fi

RESULTS_DIR="$(cd "${RESULTS_DIR}" && pwd)"
echo "=========================================="
echo "Jumpy-hand QC (host Python)"
echo "=========================================="
echo "Results dir: ${RESULTS_DIR}"
echo ""

# Step 1: Detect jumpy hands (writes qc_results per run + qc_world_jumpy_batch_summary.json in results_dir)
echo "Step 1: Running detect_jumpy_hand_from_world_results.py ..."
python3 "${SCRIPT_DIR}/detect_jumpy_hand_from_world_results.py" \
    --world_results_dir "${RESULTS_DIR}" \
    --json \
    --plot \
    --trans_factor "${TRANS_FACTOR}" \
    --rot_factor "${ROT_FACTOR}" \
    --error_threshold_factor_trans 10.0 \
    --error_threshold_factor_rot 10.0 \
    --error_valid_ratio 0.3

SUMMARY="${RESULTS_DIR}/qc_world_jumpy_batch_summary.json"
if [ ! -f "${SUMMARY}" ]; then
    echo "No batch summary produced (no matching world_results found?). Skipping proportions."
    exit 0
fi

# Step 2: Compute proportions from batch summary
echo ""
echo "Step 2: Running cal_jumpy_proportions.py ..."
EXTRA=""
[ -n "${FPS}" ] && EXTRA="${EXTRA} --fps ${FPS}"
python3 "${SCRIPT_DIR}/cal_jumpy_proportions.py" --world_results_dir "${RESULTS_DIR}" ${EXTRA}

echo ""
echo "=========================================="
echo "Jumpy-hand QC done."
echo "=========================================="
echo "  Batch summary: ${SUMMARY}"
echo "  Per-run QC:    <each run>/qc_results/"
echo "  Proportions:   printed above; use --out <path> in cal_jumpy_proportions.py to save JSON."
