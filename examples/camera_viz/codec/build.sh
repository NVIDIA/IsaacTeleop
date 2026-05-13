#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# One-shot build for the camera_viz native codec. The resulting
# _camera_viz_codec.so lands next to __init__.py so the package is
# importable straight from the source tree — no install step.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
build_dir="${here}/build"

# Pin to /usr/local/cuda if present — Ubuntu's /usr/bin/nvcc is CUDA 11.5
# which doesn't accept modern sm_* architectures anymore. The CUDA
# toolkit installed under /usr/local/cuda is the one CMake's
# FindCUDAToolkit should pick.
if [[ -z "${CUDACXX:-}" && -x /usr/local/cuda/bin/nvcc ]]; then
    export CUDACXX=/usr/local/cuda/bin/nvcc
    export CUDA_PATH=/usr/local/cuda
    export PATH="/usr/local/cuda/bin:${PATH}"
fi

# Sanity-check the active venv. The CMake configure shells out to
# `python -c "import pybind11"` and we want that to be the camera_viz
# venv's python, not /usr/bin/python3.
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "build.sh: no active venv — activate examples/camera_viz/.venv first" >&2
    echo "  source examples/camera_viz/.venv/bin/activate" >&2
    exit 1
fi
if ! python -c "import pybind11" 2>/dev/null; then
    echo "build.sh: pybind11 not in venv — installing..." >&2
    uv pip install pybind11
fi

# Use ninja if available — faster reconfigures.
generator=()
if command -v ninja >/dev/null 2>&1; then
    generator=(-G Ninja)
fi

cmake -S "${here}" -B "${build_dir}" "${generator[@]}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DPython3_EXECUTABLE="$(command -v python)"

cmake --build "${build_dir}" --parallel

echo
echo "build.sh: codec built → ${here}/_camera_viz_codec*.so"
