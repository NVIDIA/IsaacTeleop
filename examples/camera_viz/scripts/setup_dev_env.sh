#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# setup_dev_env.sh — one-shot installer for the camera_viz dev venv.
# Creates ${REPO}/examples/camera_viz/.venv (or --venv PATH), installs the
# IsaacTeleop wheel from build/wheels/ plus every dep camera_viz +
# camera_streamer need to run on a desktop. Idempotent: re-running upgrades.
#
# After it finishes:
#   source examples/camera_viz/.venv/bin/activate
#   python examples/camera_viz/camera_viz.py examples/camera_viz/configs/v4l2.yaml
#   # or:
#   examples/camera_viz/scripts/loopback.sh examples/camera_viz/configs/v4l2.yaml
#
# Usage:
#   setup_dev_env.sh [--venv PATH] [--wheel PATH] [--python VER]
#                    [--no-v4l2] [--no-oakd] [--no-rtp] [--with-zed]
#                    [--zed-sdk PATH]

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
CAMERA_VIZ_DIR=$(cd "$(dirname "$0")/.." && pwd)

VENV_DIR="$CAMERA_VIZ_DIR/.venv"
PYTHON_VERSION=3.12
WHEEL=
WITH_V4L2=true
WITH_OAKD=true
WITH_RTP=true
WITH_ZED=false
ZED_SDK_DIR=/usr/local/zed
SYSTEM_SITE_PACKAGES=false

while (( $# )); do
    case $1 in
        --venv)     VENV_DIR=$2; shift 2;;
        --wheel)    WHEEL=$2; shift 2;;
        --python)   PYTHON_VERSION=$2; shift 2;;
        --no-v4l2)  WITH_V4L2=false; shift;;
        --no-oakd)  WITH_OAKD=false; shift;;
        --no-rtp)   WITH_RTP=false; shift;;
        --with-zed) WITH_ZED=true; shift;;
        --zed-sdk)  ZED_SDK_DIR=$2; shift 2;;
        --system-site-packages) SYSTEM_SITE_PACKAGES=true; shift;;
        -h|--help)
            sed -n '3,/^$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

# Resolve the wheel: latest match in build/wheels/ unless --wheel given.
if [[ -z "$WHEEL" ]]; then
    WHEEL=$(ls -1 "$REPO_ROOT"/build/wheels/isaacteleop-*.whl 2>/dev/null | head -1 || true)
fi
[[ -n "$WHEEL" && -f "$WHEEL" ]] || {
    echo "setup_dev_env.sh: no wheel found." >&2
    echo "  Build one with: cmake --build build --target python_wheel" >&2
    echo "  Or pass --wheel <path>." >&2
    exit 1
}

command -v uv >/dev/null || {
    echo "setup_dev_env.sh: 'uv' not on PATH. Install it from https://docs.astral.sh/uv/" >&2
    exit 1
}

echo "==> venv:    $VENV_DIR"
echo "==> python:  $PYTHON_VERSION"
echo "==> wheel:   $WHEEL"

# Create the venv idempotently. ``uv venv`` recreates if the Python version
# differs; otherwise it's a no-op and we just install on top.
if [[ ! -d "$VENV_DIR" ]]; then
    VENV_FLAGS=()
    $SYSTEM_SITE_PACKAGES && VENV_FLAGS+=(--system-site-packages)
    uv venv "$VENV_DIR" --python "$PYTHON_VERSION" "${VENV_FLAGS[@]}"
fi
PY="$VENV_DIR/bin/python"

# Build the install list. Mirrors the dependency + optional-dependency blocks
# in pyproject.toml — keep in sync if you edit one or the other.
PKGS=("$WHEEL" "pyyaml>=6.0" "cupy-cuda12x" "numpy>=1.23" "scipy>=1.15")
$WITH_V4L2 && PKGS+=("opencv-python>=4.5")
$WITH_OAKD && PKGS+=("depthai>=3.0")
# PyGObject pinned <3.51: 3.51+ requires girepository-2.0 (GLib ≥2.80) which
# Ubuntu 22.04 LTS doesn't ship. Drop the cap when 22.04 isn't a target.
# pybind11 is the build-time dep for the native codec at ./codec/ — keep in
# the runtime venv so the user can iterate on codec/*.cpp without reinstalling.
$WITH_RTP  && PKGS+=("PyGObject>=3.40,<3.51" "pybind11>=2.11")

echo "==> installing: ${PKGS[*]}"
uv pip install --python "$PY" --upgrade "${PKGS[@]}"

# ZED SDK's get_python_api.py downloads a pyzed wheel matching the active
# Python. We run it inside the venv-Python, expect its internal `pip install`
# to fail (uv venvs don't ship pip), then install the leftover wheel ourselves.
if $WITH_ZED; then
    if [[ ! -f "$ZED_SDK_DIR/get_python_api.py" ]]; then
        echo "setup_dev_env.sh: --with-zed but no $ZED_SDK_DIR/get_python_api.py. " \
             "Install the ZED SDK first or pass --zed-sdk <dir>." >&2
        exit 1
    fi
    echo "==> fetching pyzed via $ZED_SDK_DIR/get_python_api.py"
    # The SDK script imports ``requests`` for the download and shells
    # out to ``pip install`` afterwards. We install requests up front;
    # the pip-install step fails on uv venvs (no pip), which is fine —
    # we install the downloaded wheel ourselves below.
    uv pip install --python "$PY" --quiet requests
    tmp=$(mktemp -d)
    pushd "$tmp" >/dev/null
    "$PY" "$ZED_SDK_DIR/get_python_api.py" || true
    pyzed_whl=$(ls -1 pyzed-*.whl 2>/dev/null | head -1 || true)
    if [[ -z "$pyzed_whl" ]]; then
        popd >/dev/null
        echo "setup_dev_env.sh: get_python_api.py did not produce a wheel." >&2
        rm -rf "$tmp"
        exit 1
    fi
    uv pip install --python "$PY" --upgrade "$tmp/$pyzed_whl"
    popd >/dev/null
    rm -rf "$tmp"
fi

# Build the native NVENC/NVDEC codec for the RTP path. Requires CUDA
# toolkit + NVIDIA driver. Skipped under --no-rtp.
if $WITH_RTP; then
    echo "==> building native codec (examples/camera_viz/codec)"
    CODEC_DIR="$(cd "$(dirname "$0")/.." && pwd)/codec"
    if [[ ! -d "$CODEC_DIR" ]]; then
        echo "setup_dev_env.sh: $CODEC_DIR not found — skipping codec build" >&2
    else
        # Run the codec build inside the venv we just provisioned.
        # build.sh checks VIRTUAL_ENV; activating here keeps that check
        # green and ensures pybind11 / Python come from the right place.
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"
        if ! "$CODEC_DIR/build.sh"; then
            echo "setup_dev_env.sh: codec build failed — RTP encode/decode will not work" >&2
            echo "                 see errors above; rerun ./codec/build.sh once fixed" >&2
        fi
        deactivate
    fi
fi

# Quick smoke: every module the example needs at import time.
echo "==> import smoke"
"$PY" - <<'PY'
import sys
mods = ["isaacteleop.viz", "cupy", "yaml", "scipy.spatial.transform"]
fail = []
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        fail.append((m, e))
for m, e in fail:
    print(f"  FAIL {m}: {e}", file=sys.stderr)
print("  OK" if not fail else "  some imports failed (see above)")
sys.exit(0 if not fail else 1)
PY

cat <<EOF

Setup done.

  source $VENV_DIR/bin/activate
  python examples/camera_viz/camera_viz.py examples/camera_viz/configs/v4l2.yaml
  # or loopback the full sender/receiver pair on this host:
  examples/camera_viz/scripts/loopback.sh examples/camera_viz/configs/v4l2.yaml
EOF
