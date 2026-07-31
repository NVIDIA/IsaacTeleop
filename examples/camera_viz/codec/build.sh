#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Builds the native NVENC/NVDEC codec. The .so lands next to
# __init__.py so the package imports straight from the source tree.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
build_dir="${here}/build"

# Prefer /usr/local/cuda's nvcc — distro nvcc is often too old for
# modern compute capabilities.
if [[ -z "${CUDACXX:-}" && -x /usr/local/cuda/bin/nvcc ]]; then
    export CUDACXX=/usr/local/cuda/bin/nvcc
    export CUDA_PATH=/usr/local/cuda
    export PATH="/usr/local/cuda/bin:${PATH}"
fi

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "build.sh: no active venv — activate examples/camera_viz/.venv first" >&2
    exit 1
fi
if ! python -c "import pybind11" 2>/dev/null; then
    echo "build.sh: installing pybind11 into venv..." >&2
    uv pip install pybind11
fi

generator=()
if command -v ninja >/dev/null 2>&1; then
    generator=(-G Ninja)
fi

# A failed configure before CUDA is installed leaves CMake's compiler-feature
# cache incomplete.  Clear generated CMake state on every setup retry, but
# keep build/_deps and the downloaded Video Codec SDK to avoid another fetch.
cmake -E rm -f "${build_dir}/CMakeCache.txt"
cmake -E rm -rf "${build_dir}/CMakeFiles"

cmake -S "${here}" -B "${build_dir}" "${generator[@]}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DPython3_EXECUTABLE="$(command -v python)"
cmake --build "${build_dir}" --parallel

echo
echo "build.sh: codec built → ${here}/_camera_viz_codec*.so"
