#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Host-side wrapper that runs mesh generation inside the Dyn-HaMR container.
# Expects Dyn-HaMR reconstruction results under OUTPUTS_DIR/logs/.../<PHASE>/*_world_results.npz.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUTS_DIR="${OUTPUTS_DIR:-${PROJECT_ROOT}/outputs}"

PHASE="${PHASE:-smooth_fit}"
GPU="${GPU:-0}"
NO_TEMPORAL_SMOOTH="${NO_TEMPORAL_SMOOTH:-0}"
NO_SMOOTH_TRANS="${NO_SMOOTH_TRANS:-0}"

if [ ! -d "${OUTPUTS_DIR}" ]; then
    echo "Error: outputs directory not found: ${OUTPUTS_DIR}"
    echo "Run scripts/run_reconstruction.sh first, or set OUTPUTS_DIR."
    exit 1
fi

# MANO_RIGHT.pkl lives on the host in OUTPUTS_DIR/; setup_dynhamr.sh copies it
# into the container's _DATA/data/mano/ on first run. Gate here for a clear error.
if [ ! -f "${OUTPUTS_DIR}/MANO_RIGHT.pkl" ]; then
    echo "Error: MANO_RIGHT.pkl not found in ${OUTPUTS_DIR}/"
    echo "Download from https://mano.is.tue.mpg.de/ and place at ${OUTPUTS_DIR}/MANO_RIGHT.pkl"
    exit 1
fi

echo "=========================================="
echo "Hand mesh generation (via Dyn-HaMR container)"
echo "=========================================="
echo "Outputs dir: ${OUTPUTS_DIR}"
echo "Phase:       ${PHASE}"
echo "GPU:         ${GPU}"
echo ""

OUTPUTS_DIR="${OUTPUTS_DIR}" "${PROJECT_ROOT}/docker/dynhamr.sh" run bash -c "
    # Ensure MANO is populated inside the container (idempotent).
    bash /home/appuser/setup_dynhamr.sh >/dev/null

    PHASE='${PHASE}' \
    GPU='${GPU}' \
    NO_TEMPORAL_SMOOTH='${NO_TEMPORAL_SMOOTH}' \
    NO_SMOOTH_TRANS='${NO_SMOOTH_TRANS}' \
    bash /home/appuser/Dyn-HaMR/dyn-hamr/generate_mesh.sh /home/appuser/outputs
"

echo ""
echo "=========================================="
echo "Mesh generation complete."
echo "=========================================="
echo "Hand mesh .npz files written alongside world_results under ${OUTPUTS_DIR}/logs/"
