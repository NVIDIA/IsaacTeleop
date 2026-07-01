#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

APT_PACKAGES=(
    build-essential
    cmake
    libx11-dev
    clang-format-14
    ccache
    patchelf
    android-tools-adb
    coturn
)

run_as_root() {
    if [[ "$(id -u)" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

missing_packages=()
for package in "${APT_PACKAGES[@]}"; do
    status=$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)
    if [[ "$status" != "install ok installed" ]]; then
        missing_packages+=("$package")
    fi
done

if [[ "${#missing_packages[@]}" -gt 0 ]]; then
    echo "Installing missing IsaacTeleop build packages: ${missing_packages[*]}"
    run_as_root apt-get update
    run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing_packages[@]}"
else
    echo "All IsaacTeleop build packages are already installed."
fi

rm -rf build
cmake -B build \
    -DISAAC_TELEOP_PYTHON_VERSION=3.10 \
    -DBUILD_EXAMPLES=OFF \
    -DBUILD_TESTING=OFF \
    -DENABLE_CLANG_FORMAT_CHECK=OFF
cmake --build build --parallel