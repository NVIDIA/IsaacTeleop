#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Build the Wuji glove plugin.
#
# Two steps: (1) fetch the released wuji_sdk C SDK the plugin links against,
# (2) configure + build the plugin target. The explicit fetch keeps the vendor
# SDK out of normal builds when this optional plugin is disabled.
#
# Usage:
#   ./install.sh [<isaacteleop-root>]
#
# Env:
#   WUJI_SDK_C_DIR      skip the download and use an already-extracted C SDK dir
#                       (must contain include/wuji_sdk.h + the SDK shared libs).
#
# The C SDK ships as a public GitHub release asset — plain curl, no auth needed.
# Set WUJI_SDK_C_DIR to a local copy to build offline.

set -euo pipefail

WUJI_SDK_C_VERSION="2026.7.14"
WUJI_SDK_C_URL_BASE="https://github.com/wuji-technology/wuji-sdk/releases/download"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISAAC_ROOT="${1:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
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
    work="$(mktemp -d)"
    echo "==> Downloading ${name}.tar.gz"
    curl -fL --retry 3 "$url" -o "$work/${name}.tar.gz" \
        || { echo "download failed: $url" >&2; exit 1; }
    tar -xzf "$work/${name}.tar.gz" -C "$work"
    sdk_dir="$work/$name"
fi

wuji_sdk_include_dir="$sdk_dir/include"
wuji_sdk_lib="$sdk_dir/lib/libwuji_sdk_c.so"
wuji_hand_cpp_lib="$sdk_dir/lib/libwujihandcpp.so"
[[ -f "$wuji_sdk_include_dir/wuji_sdk.h" && -f "$wuji_sdk_lib" && -f "$wuji_hand_cpp_lib" ]] || {
    echo "wuji_sdk C SDK not found under $sdk_dir (need include/wuji_sdk.h and both SDK shared libs)" >&2
    exit 1
}

# 2. Configure + build the plugin target.
echo "==> Building wuji_glove_plugin"
cmake -B "$ISAAC_ROOT/build" -S "$ISAAC_ROOT" -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_PLUGIN_WUJI_GLOVE=ON \
    -DWUJI_SDK_INCLUDE_DIR="$wuji_sdk_include_dir" \
    -DWUJI_SDK_LIB="$wuji_sdk_lib"
cmake --build "$ISAAC_ROOT/build" --target wuji_glove_plugin --parallel

# Co-locate the metadata and vendor library with the build-tree binary. CMake's
# $ORIGIN build RPATH then keeps the plugin runnable after the download temp dir
# is cleaned up; `cmake --install` uses install/lib instead.
cp "$SCRIPT_DIR/plugin.yaml" "$ISAAC_ROOT/build/src/plugins/wuji_glove/"
cp "$wuji_sdk_lib" "$wuji_hand_cpp_lib" "$ISAAC_ROOT/build/src/plugins/wuji_glove/"

echo "==> Done: $ISAAC_ROOT/build/src/plugins/wuji_glove/wuji_glove_plugin"
