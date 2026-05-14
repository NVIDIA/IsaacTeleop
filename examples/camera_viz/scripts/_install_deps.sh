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

# Detect CUDA major from /usr/local/cuda's resolved target (typically
# /usr/local/cuda → /etc/alternatives/cuda → /usr/local/cuda-13.0).
# Default to 12 when nothing's detectable. Used for both the cupy
# wheel name and the cuda-nvrtc apt package version.
cuda_major=12
if [[ -e /usr/local/cuda ]]; then
    cuda_resolved=$(readlink -f /usr/local/cuda 2>/dev/null)
    detected=$(echo "$cuda_resolved" | grep -oE 'cuda-[0-9]+' | head -1 | cut -d- -f2)
    [[ -n "$detected" ]] && cuda_major=$detected
fi

# System apt deps: Debian PyGObject + GStreamer (so we don't source-build
# pycairo / PyGObject) plus cuda-nvrtc, which JetPack 7's base image
# doesn't ship — cupy can't compile kernels without it. Idempotent;
# skipped fast when nothing is missing.
ensure_apt_deps() {
    if ! $WITH_RTP; then
        return 0
    fi
    if ! command -v apt-get >/dev/null 2>&1; then
        return 0  # not Debian/Ubuntu, user is on their own
    fi

    local pkgs=()
    if ! python3 -c "import gi; gi.require_version('Gst', '1.0'); from gi.repository import Gst" 2>/dev/null; then
        pkgs+=(
            python3-gi
            python3-gst-1.0
            gir1.2-gstreamer-1.0
            gstreamer1.0-tools
            gstreamer1.0-plugins-base
            gstreamer1.0-plugins-good
        )
    fi
    # NVRTC is the kernel compiler cupy uses at runtime. JetPack 7 omits
    # it from the base CUDA toolkit metapackages; install it explicitly.
    if ! find /usr -name 'libnvrtc.so*' 2>/dev/null | grep -q .; then
        pkgs+=("cuda-nvrtc-${cuda_major}-0")
    fi

    if [[ ${#pkgs[@]} -eq 0 ]]; then
        return 0
    fi
    echo "==> apt-installing system deps: ${pkgs[*]}"
    if ! sudo -n true 2>/dev/null; then
        echo "    sudo password required (one-time)"
    fi
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${pkgs[@]}"
}
ensure_apt_deps

# JetPack's cuda-nvrtc-13-0 lays down libnvrtc.so.13 in /usr/local/cuda/
# lib64 but skips the unversioned symlink and the ld.so cache entry that
# the desktop CUDA installer normally creates. cupy + cuda.pathfinder
# both look for ``libnvrtc.so`` (no version) and resolve via ld.so, so
# without the symlink + cache entry the load fails with "No such file:
# libnvrtc.so*" even though the .so.13 sits right there.
ensure_cuda_symlinks() {
    if [[ ! -d /usr/local/cuda/lib64 ]]; then
        return 0
    fi
    local lib64=/usr/local/cuda/lib64
    local needs_sudo=false
    for stem in libnvrtc.so libnvrtc-builtins.so libcudart.so; do
        if [[ ! -e "$lib64/$stem" ]]; then
            local versioned
            versioned=$(ls "$lib64/$stem".[0-9]* 2>/dev/null | sort -V | tail -1)
            [[ -n "$versioned" ]] && needs_sudo=true
        fi
    done
    if ! ldconfig -p 2>/dev/null | grep -q "$lib64"; then
        needs_sudo=true
    fi
    if ! $needs_sudo; then
        return 0
    fi

    echo "==> wiring CUDA libs into ld.so + creating unversioned symlinks"
    if ! sudo -n true 2>/dev/null; then
        echo "    sudo password required (one-time)"
    fi
    for stem in libnvrtc.so libnvrtc-builtins.so libcudart.so; do
        if [[ ! -e "$lib64/$stem" ]]; then
            local versioned
            versioned=$(ls "$lib64/$stem".[0-9]* 2>/dev/null | sort -V | tail -1)
            if [[ -n "$versioned" ]]; then
                sudo ln -sf "$(basename "$versioned")" "$lib64/$stem"
                echo "    $lib64/$stem -> $(basename "$versioned")"
            fi
        fi
    done
    if ! ldconfig -p 2>/dev/null | grep -q "$lib64"; then
        echo "$lib64" | sudo tee /etc/ld.so.conf.d/zz-camera-viz-cuda.conf >/dev/null
        sudo ldconfig
        echo "    registered $lib64 with ldconfig"
    fi
}
ensure_cuda_symlinks

# Auto-install uv into ~/.local/bin if missing. Jetson images usually
# don't ship it; we don't want a fresh deploy to require a manual step.
if ! command -v uv >/dev/null 2>&1; then
    if [[ -x "$HOME/.local/bin/uv" ]]; then
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo "==> installing uv (no system uv found)"
        if ! command -v curl >/dev/null 2>&1; then
            echo "_install_deps.sh: 'curl' required to bootstrap uv. apt install curl." >&2
            exit 1
        fi
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
        command -v uv >/dev/null || {
            echo "_install_deps.sh: uv install failed — check ~/.local/bin/uv." >&2
            exit 1
        }
    fi
fi

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
    # --system-site-packages lets the venv see Debian's apt-packaged
    # python3-gi / python3-gst-1.0 without rebuilding them from source.
    # Venv-installed packages still shadow system ones (venv site-packages
    # is prepended to sys.path).
    #
    # Critical: in --sender-only mode we base the venv on the SYSTEM
    # python3, not uv's managed download. --system-site-packages exposes
    # whichever interpreter's site-packages the base points at, and only
    # the system python3 sees /usr/lib/python3/dist-packages (where
    # python3-gi lands). Full mode pins by version since it needs to
    # match the IsaacTeleop wheel's ABI.
    if [[ "$MODE" == sender ]]; then
        sys_py="$(command -v python3 || true)"
        [[ -x "$sys_py" ]] || {
            echo "_install_deps.sh: system python3 required in --sender-only mode" >&2
            exit 1
        }
        uv venv "$VENV_DIR" --python "$sys_py" --system-site-packages
    else
        uv venv "$VENV_DIR" --python "$PYTHON_VERSION" --system-site-packages
    fi
fi
PY="$VENV_DIR/bin/python"

echo "==> cuda:   $cuda_major (cupy-cuda${cuda_major}x)"

# Mirrors pyproject.toml's dependency block. Sender-only drops the wheel.
# PyGObject is intentionally NOT here — it comes from system python3-gi
# via --system-site-packages above.
PKGS=("pyyaml>=6.0" "cupy-cuda${cuda_major}x" "numpy>=1.23" "scipy>=1.15")
[[ "$MODE" == full ]] && PKGS=("$WHEEL" "${PKGS[@]}")
$WITH_V4L2 && PKGS+=("opencv-python>=4.5")
$WITH_OAKD && PKGS+=("depthai>=3.0")
$WITH_RTP  && PKGS+=("pybind11>=2.11")

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

# Smoke import — kept minimal so this works in --sender-only too. ``gi``
# is included when RTP is enabled to verify --system-site-packages
# actually exposes the apt-installed PyGObject.
echo "==> import smoke"
SMOKE_MODS="cupy yaml scipy.spatial.transform"
[[ "$MODE" == full ]] && SMOKE_MODS="isaacteleop.viz $SMOKE_MODS"
$WITH_RTP && SMOKE_MODS="$SMOKE_MODS gi"
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
