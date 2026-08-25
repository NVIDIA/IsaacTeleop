#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Install the Wuji glove plugin.
#
# Two steps: (1) fetch the released wuji_sdk C SDK the plugin links against,
# (2) configure, build, and install the plugin target. The explicit fetch keeps
# the vendor SDK out of normal builds when this optional plugin is disabled.
#
# Usage:
#   ./install.sh [--build-dir <path>] [<isaacteleop-root>]
#
# Env:
#   WUJI_SDK_C_DIR      skip the download and use an already-extracted C SDK dir
#                       (must contain include/wuji_sdk.h + the SDK shared libs).
#
# The C SDK ships as a public GitHub release asset — plain curl, no auth needed.
# The tarball is verified against a pinned per-arch SHA-256, then extracted next
# to this script so the paths baked into the CMake cache stay valid across
# reconfigures and `cmake --install`; re-runs reuse the extracted copy.
# Set WUJI_SDK_C_DIR to a local copy to build offline.

set -euo pipefail

WUJI_SDK_C_VERSION="2026.7.14"
WUJI_SDK_C_URL_BASE="https://github.com/wuji-technology/wuji-sdk/releases/download"
# Pinned SHA-256 per release asset; update together with WUJI_SDK_C_VERSION
# (digests are published in the GitHub release metadata).
declare -A WUJI_SDK_C_SHA256=(
    ["x86_64-linux-gnu"]="5217e51a88c8c9c4055669f8a3f856e5ec2242bc72a0383a5b9d39479e32c0b1"
    ["aarch64-linux-gnu"]="66f1562a7f6f8c3d2cff932f9d86a6e03c24d3557fb57ab3f9f3308e4b49069c"
)

build_dir=""
isaac_root=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir)
            build_dir="${2:?--build-dir requires a non-empty path}"
            shift 2
            ;;
        -h | --help)
            cat <<EOF
Usage: $(basename "$0") [--build-dir <path>] [<isaacteleop-root>]

Downloads the Wuji C SDK, then builds and installs the glove plugin.

Options:
  --build-dir <path>  CMake build directory (default: <isaacteleop-root>/build).
  -h, --help          Show this help.
EOF
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            if [[ -n "$isaac_root" ]]; then
                echo "Only one Isaac Teleop root may be specified" >&2
                exit 1
            fi
            isaac_root="$1"
            shift
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISAAC_ROOT="${isaac_root:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
BUILD_DIR="${build_dir:-$ISAAC_ROOT/build}"
if [[ "$BUILD_DIR" != /* ]]; then
    BUILD_DIR="$PWD/$BUILD_DIR"
fi
work=""
trap '[[ -z "$work" ]] || rm -rf "$work"' EXIT

# 1. wuji_sdk C SDK (headers + libwuji_sdk_c.so).
if [[ -n "${WUJI_SDK_C_DIR:-}" ]]; then
    sdk_dir="$WUJI_SDK_C_DIR"
    echo "==> Using pre-extracted wuji_sdk C SDK: $sdk_dir"
else
    case "$(uname -m)" in
        aarch64 | arm64) arch="aarch64-linux-gnu" ;;
        x86_64) arch="x86_64-linux-gnu" ;;
        *)
            echo "unsupported arch: $(uname -m)" >&2
            exit 1
            ;;
    esac
    name="wuji-sdk-c-${WUJI_SDK_C_VERSION}-${arch}"
    url="${WUJI_SDK_C_URL_BASE}/v${WUJI_SDK_C_VERSION}/${name}.tar.gz"
    sdk_dir="$SCRIPT_DIR/$name"
    if [[ -f "$sdk_dir/include/wuji_sdk.h" && -f "$sdk_dir/lib/libwuji_sdk_c.so" \
        && -f "$sdk_dir/lib/libwujihandcpp.so" ]]; then
        echo "==> Reusing extracted wuji_sdk C SDK: $sdk_dir"
    else
        work="$(mktemp -d)"
        echo "==> Downloading ${name}.tar.gz"
        curl -fL --retry 3 "$url" -o "$work/${name}.tar.gz" \
            || { echo "download failed: $url" >&2; exit 1; }
        actual_sha256="$(sha256sum "$work/${name}.tar.gz" | awk '{print $1}')"
        expected_sha256="${WUJI_SDK_C_SHA256[$arch]}"
        if [[ "$actual_sha256" != "$expected_sha256" ]]; then
            echo "SHA-256 mismatch for ${name}.tar.gz" >&2
            echo "  expected: $expected_sha256" >&2
            echo "  actual:   $actual_sha256" >&2
            exit 1
        fi
        rm -rf "$sdk_dir"
        tar -xzf "$work/${name}.tar.gz" -C "$SCRIPT_DIR"
    fi
fi

wuji_sdk_include_dir="$sdk_dir/include"
wuji_sdk_lib="$sdk_dir/lib/libwuji_sdk_c.so"
wuji_hand_cpp_lib="$sdk_dir/lib/libwujihandcpp.so"
[[ -f "$wuji_sdk_include_dir/wuji_sdk.h" && -f "$wuji_sdk_lib" && -f "$wuji_hand_cpp_lib" ]] || {
    echo "wuji_sdk C SDK not found under $sdk_dir (need include/wuji_sdk.h and both SDK shared libs)" >&2
    exit 1
}

# 2. Configure, build, and install the plugin target.
echo "==> Building wuji_glove_plugin"
cmake -B "$BUILD_DIR" -S "$ISAAC_ROOT" -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_PLUGINS=ON \
    -DBUILD_PLUGIN_WUJI_GLOVE=ON \
    -DWUJI_SDK_INCLUDE_DIR="$wuji_sdk_include_dir" \
    -DWUJI_SDK_LIB="$wuji_sdk_lib"
cmake --build "$BUILD_DIR" --target wuji_glove_plugin --parallel

# Co-locate the metadata and vendor libraries with the build-tree binary so the
# $ORIGIN build RPATH resolves them regardless of where the SDK was extracted;
# `cmake --install` lays them out the same way under plugins/wuji_glove/.
cp "$SCRIPT_DIR/plugin.yaml" "$BUILD_DIR/src/plugins/wuji_glove/"
cp "$wuji_sdk_lib" "$wuji_hand_cpp_lib" "$BUILD_DIR/src/plugins/wuji_glove/"
cmake --install "$BUILD_DIR" --component wuji_glove

install_prefix="$(awk '/^CMAKE_INSTALL_PREFIX:PATH=/{sub(/^[^=]*=/, ""); print; exit}' "$BUILD_DIR/CMakeCache.txt")"
echo "==> Done: $install_prefix/plugins/wuji_glove/wuji_glove_plugin"
