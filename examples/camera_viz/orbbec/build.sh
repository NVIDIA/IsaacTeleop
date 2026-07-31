#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
sdk_root="${ORBBEC_SDK_ROOT:-}"
while (( $# )); do
    case $1 in
        --orbbec-sdk-root) sdk_root=$2; shift 2;;
        *) echo "build.sh: unknown argument: $1" >&2; exit 1;;
    esac
done
if [[ -z "$sdk_root" ]]; then
    echo "build.sh: --orbbec-sdk-root PATH (or ORBBEC_SDK_ROOT) is required" >&2
    exit 1
fi
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "build.sh: activate examples/camera_viz/.venv first" >&2
    exit 1
fi

generator=()
if command -v ninja >/dev/null 2>&1; then
    generator=(-G Ninja)
fi
cmake -S "$here" -B "$here/build" "${generator[@]}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DPython3_EXECUTABLE="$(command -v python)" \
    -DORBBEC_SDK_ROOT="$sdk_root"
cmake --build "$here/build" --parallel
