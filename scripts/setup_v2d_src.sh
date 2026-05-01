#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Populate deps/v2d/src/robotic_grounding/ with V2D's robotic_grounding
# Python package at the SHA pinned in deps/v2d/version.txt.
#
# CMake (src/core/python/CMakeLists.txt) detects deps/v2d/src/robotic_grounding/
# at configure time and, if present, copies the subtree into the wheel
# staging dir. The resulting Teleop wheel ships robotic_grounding alongside
# isaacteleop, so `pip install isaacteleop[grounding]` Just Works -- no
# separate wheel install. deps/v2d/src/ is gitignored so V2D source never
# enters Teleop's git history.
#
# Requires:
#   * gh CLI installed and `gh auth login`'d with read access to
#     jiwenc-nv/v2d (or whichever fork holds the retargeter branch).
#
# Usage:
#   scripts/setup_v2d_src.sh
#   cmake -B build && cmake --build build  # picks up deps/v2d/src/

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

VERSION_FILE="deps/v2d/version.txt"
if [ ! -f "${VERSION_FILE}" ]; then
    echo "error: ${VERSION_FILE} is missing." >&2
    exit 1
fi

V2D_REF=$(grep -vE '^\s*(#|$)' "${VERSION_FILE}" | head -1 | tr -d '[:space:]')
if [ -z "${V2D_REF}" ]; then
    echo "error: ${VERSION_FILE} contains no SHA." >&2
    exit 1
fi
echo "Pinned V2D ref: ${V2D_REF}"

if ! command -v gh >/dev/null 2>&1; then
    echo "error: gh CLI not found. Install from https://cli.github.com/" >&2
    echo "       and run 'gh auth login' with read access to jiwenc-nv/v2d." >&2
    exit 1
fi

DST="deps/v2d/src/robotic_grounding"
mkdir -p deps/v2d/src
rm -rf "${DST}"

# Whole retargeter branch is ~25 MB so a normal clone is fine. Clone the
# branch tip then check out the exact pinned SHA.
WORK_DIR=$(mktemp -d -t v2d-src.XXXXXX)
trap 'rm -rf "${WORK_DIR}"' EXIT
gh repo clone jiwenc-nv/v2d "${WORK_DIR}/v2d" -- --branch retargeter
git -C "${WORK_DIR}/v2d" checkout "${V2D_REF}"

cp -a \
    "${WORK_DIR}/v2d/robotic_grounding/source/robotic_grounding/robotic_grounding" \
    "${DST}"
# Drop bytecode caches if any slipped through.
find "${DST}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

echo "Done -> ${DST} (cloned from jiwenc-nv/v2d @ ${V2D_REF})"
