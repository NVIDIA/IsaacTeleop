#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# _install_deps.sh — provisions the camera_viz Python venv + native codec.
# Called by ``camera_viz.sh setup`` (locally) and ``camera_viz.sh deploy``
# (remotely over SSH). Not intended for direct invocation by users.
#
# Modes:
#   --full         viewer + sender (workstation default). Installs
#                  isaacteleop wheel from build/wheels/.
#   --sender-only  sender path only. Skips the wheel + vulkan deps;
#                  used on Jetson robots where camera_streamer.py runs
#                  but camera_viz.py does not.
#
# Other flags mirror the previous setup_dev_env.sh: --venv, --wheel,
# --python, --no-v4l2, --no-oakd, --no-rtp, --with-zed, --zed-sdk.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CAMERA_VIZ_DIR="$(cd "$HERE/.." && pwd)"

# In the local workstation flow, the wheel lives in REPO_ROOT/build/wheels/.
# Resolve only when the layout looks right; over SSH on a robot, there's
# no repo around the source tree and that's fine — --sender-only doesn't
# need a wheel.
REPO_ROOT=""
if [[ -d "$CAMERA_VIZ_DIR/../.." ]]; then
    REPO_ROOT="$(cd "$CAMERA_VIZ_DIR/../.." && pwd)"
fi

MODE=full
VENV_DIR="$CAMERA_VIZ_DIR/.venv"
PYTHON_VERSION=3.12
WHEEL=
WITH_V4L2=true
WITH_OAKD=true
WITH_RTP=true
WITH_ZED=false
ZED_SDK_DIR=/usr/local/zed

while (( $# )); do
    case $1 in
        --full)         MODE=full; shift;;
        --sender-only)  MODE=sender; shift;;
        --venv)         VENV_DIR=$2; shift 2;;
        --wheel)        WHEEL=$2; shift 2;;
        --python)       PYTHON_VERSION=$2; shift 2;;
        --no-v4l2)      WITH_V4L2=false; shift;;
        --no-oakd)      WITH_OAKD=false; shift;;
        --no-rtp)       WITH_RTP=false; shift;;
        --with-zed)     WITH_ZED=true; shift;;
        --zed-sdk)      ZED_SDK_DIR=$2; shift 2;;
        *) echo "_install_deps.sh: unknown arg: $1" >&2; exit 1;;
    esac
done

command -v uv >/dev/null || {
    echo "_install_deps.sh: 'uv' not on PATH. Install from https://docs.astral.sh/uv/" >&2
    exit 1
}

# Resolve the wheel only in --full mode.
if [[ "$MODE" == full ]]; then
    if [[ -z "$WHEEL" ]]; then
        if [[ -n "$REPO_ROOT" ]]; then
            WHEEL=$(ls -1 "$REPO_ROOT"/build/wheels/isaacteleop-*.whl 2>/dev/null | head -1 || true)
        fi
    fi
    [[ -n "$WHEEL" && -f "$WHEEL" ]] || {
        echo "_install_deps.sh: no isaacteleop wheel found." >&2
        echo "  Build one with: cmake --build build --target python_wheel" >&2
        echo "  Or pass --wheel <path>. Or use --sender-only if this is a sender host." >&2
        exit 1
    }
fi

echo "==> mode:   $MODE"
echo "==> venv:   $VENV_DIR"
echo "==> python: $PYTHON_VERSION"
[[ "$MODE" == full ]] && echo "==> wheel:  $WHEEL"

if [[ ! -d "$VENV_DIR" ]]; then
    uv venv "$VENV_DIR" --python "$PYTHON_VERSION"
fi
PY="$VENV_DIR/bin/python"

# Mirrors pyproject.toml's dependency block. Sender-only drops the wheel.
PKGS=("pyyaml>=6.0" "cupy-cuda12x" "numpy>=1.23" "scipy>=1.15")
[[ "$MODE" == full ]] && PKGS=("$WHEEL" "${PKGS[@]}")
$WITH_V4L2 && PKGS+=("opencv-python>=4.5")
$WITH_OAKD && PKGS+=("depthai>=3.0")
# PyGObject <3.51: 3.51+ requires girepository-2.0 (GLib ≥2.80) which
# Ubuntu 22.04 LTS doesn't ship.
$WITH_RTP  && PKGS+=("PyGObject>=3.40,<3.51" "pybind11>=2.11")

echo "==> installing: ${PKGS[*]}"
uv pip install --python "$PY" --upgrade "${PKGS[@]}"

# ZED SDK's get_python_api.py downloads a pyzed wheel matching the active
# Python. We run it inside the venv-Python, expect its internal pip step
# to fail (uv venvs don't ship pip), then install the leftover wheel.
if $WITH_ZED; then
    [[ -f "$ZED_SDK_DIR/get_python_api.py" ]] || {
        echo "_install_deps.sh: --with-zed but no $ZED_SDK_DIR/get_python_api.py." >&2
        echo "  Install the ZED SDK first or pass --zed-sdk <dir>." >&2
        exit 1
    }
    echo "==> fetching pyzed via $ZED_SDK_DIR/get_python_api.py"
    uv pip install --python "$PY" --quiet requests
    tmp=$(mktemp -d)
    pushd "$tmp" >/dev/null
    "$PY" "$ZED_SDK_DIR/get_python_api.py" || true
    pyzed_whl=$(ls -1 pyzed-*.whl 2>/dev/null | head -1 || true)
    if [[ -z "$pyzed_whl" ]]; then
        popd >/dev/null
        rm -rf "$tmp"
        echo "_install_deps.sh: get_python_api.py did not produce a wheel." >&2
        exit 1
    fi
    uv pip install --python "$PY" --upgrade "$tmp/$pyzed_whl"
    popd >/dev/null
    rm -rf "$tmp"
fi

# Native NVENC/NVDEC codec. Skipped under --no-rtp. On Jetson, the build
# may fail (no CUDA toolkit on some L4T images); we keep going so the
# GStreamer fallback path still works.
if $WITH_RTP; then
    CODEC_DIR="$CAMERA_VIZ_DIR/codec"
    if [[ -d "$CODEC_DIR" ]]; then
        echo "==> building native codec"
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"
        if ! "$CODEC_DIR/build.sh"; then
            echo "_install_deps.sh: codec build failed — GStreamer encoder will be used at runtime" >&2
        fi
        deactivate
    fi
fi

# Smoke import — kept minimal so this works in --sender-only too.
echo "==> import smoke"
SMOKE_MODS="cupy yaml scipy.spatial.transform"
[[ "$MODE" == full ]] && SMOKE_MODS="isaacteleop.viz $SMOKE_MODS"
"$PY" - <<PY
import sys
mods = "$SMOKE_MODS".split()
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

echo "_install_deps.sh: done."
