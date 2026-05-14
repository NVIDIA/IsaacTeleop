#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Provisions the camera_viz venv + native codec. Invoked by
# ``camera_viz.sh setup`` (local) and ``camera_viz.sh deploy`` (over SSH).
#
# Modes:
#   --full         viewer + sender (workstation). Installs isaacteleop wheel.
#   --sender-only  sender path only. No wheel, no vulkan deps.
#
# Flags: --venv, --wheel, --python, --no-v4l2, --no-oakd, --no-rtp,
#        --with-zed, --zed-sdk.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CAMERA_VIZ_DIR="$(cd "$HERE/.." && pwd)"

# Only resolved when this lives inside the IsaacTeleop tree (local flow).
# Empty on rsync'd robot deploys, which use --sender-only and don't need
# the wheel anyway.
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

# major picks the cupy wheel (cupy-cuda12x / cupy-cuda13x).
# major.minor picks the apt nvrtc package (cuda-nvrtc-12-6 on Orin/JP6,
# cuda-nvrtc-13-0 on Thor/JP7); JetPack only publishes the exact-minor.
cuda_major=12
cuda_minor=0
if [[ -e /usr/local/cuda ]]; then
    cuda_resolved=$(readlink -f /usr/local/cuda 2>/dev/null)
    full=$(echo "$cuda_resolved" | grep -oE 'cuda-[0-9]+\.[0-9]+' | head -1 | sed 's/cuda-//')
    if [[ -n "$full" ]]; then
        cuda_major=$(echo "$full" | cut -d. -f1)
        cuda_minor=$(echo "$full" | cut -d. -f2)
    fi
fi

# Apt-install: Debian PyGObject (avoids a pycairo source-build), GStreamer
# plugins, and cuda-nvrtc (JetPack base image omits it). Idempotent; each
# package is gated on a fast check.
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
            # h264parse + nv*h264enc live in -bad; both sender and receiver
            # pipelines need h264parse.
            gstreamer1.0-plugins-bad
            gstreamer1.0-libav
        )
    fi
    if ! find /usr -name 'libnvrtc.so*' 2>/dev/null | grep -q .; then
        pkgs+=("cuda-nvrtc-${cuda_major}-${cuda_minor}")
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

# JetPack ships versioned libs (libnvrtc.so.13) without the unversioned
# symlink + ld.so cache entry that desktop CUDA creates. cupy looks up
# ``libnvrtc.so`` and fails to resolve without these.
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

# Bootstrap uv from astral.sh if missing (Jetson images don't ship it).
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
    # --system-site-packages exposes Debian's python3-gi / python3-gst-1.0
    # (no pycairo source-build); venv installs still shadow system pkgs.
    # Sender mode must base on system python3 so /usr/lib/python3/dist-
    # packages is reachable — uv's managed download has empty site-packages.
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

echo "==> cuda:   ${cuda_major}.${cuda_minor} (cupy-cuda${cuda_major}x, cuda-nvrtc-${cuda_major}-${cuda_minor})"

# Mirrors pyproject.toml. PyGObject comes from system python3-gi via
# --system-site-packages, not pip.
PKGS=("pyyaml>=6.0" "cupy-cuda${cuda_major}x" "numpy>=1.23" "scipy>=1.15")
[[ "$MODE" == full ]] && PKGS=("$WHEEL" "${PKGS[@]}")
$WITH_V4L2 && PKGS+=("opencv-python>=4.5")
$WITH_OAKD && PKGS+=("depthai>=3.0")
$WITH_RTP  && PKGS+=("pybind11>=2.11")

echo "==> installing: ${PKGS[*]}"
uv pip install --python "$PY" --upgrade "${PKGS[@]}"

# ZED SDK ships get_python_api.py which downloads a matching pyzed wheel
# and then tries ``pip install`` it (which fails in uv venvs, no pip).
# We let that fail and install the wheel ourselves.
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

# Native NVENC/NVDEC codec. Failures are non-fatal: the runtime falls
# back to the GStreamer encoder when the native ``.so`` isn't importable.
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

# Smoke imports. ``gi`` is in the list under RTP to confirm
# --system-site-packages is wired up.
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
