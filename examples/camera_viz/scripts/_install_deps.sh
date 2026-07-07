#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Provisions the camera_viz venv + native codec. Invoked by
# ``camera_viz.sh setup`` (local) and ``camera_viz.sh deploy`` (over SSH).
#
# Modes:
#   --full         viewer + sender (workstation). Installs isaacteleop from PyPI
#                  (or a local --wheel).
#   --sender-only  sender path only. No isaacteleop, no vulkan deps.
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
# Jetson-specific provisioning: apt-install cuda-nvrtc and create the
# unversioned CUDA lib symlinks + ld.so cache entry that JetPack skips.
# Off on desktop where the normal CUDA installer covers both.
JETSON=false

while (( $# )); do
    case $1 in
        --full)         MODE=full; shift;;
        --sender-only)  MODE=sender; shift;;
        --jetson)       JETSON=true; shift;;
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

# System-dep check. apt-installable bits are NOT auto-installed — we
# only probe what's present and, if anything is missing, print the
# exact ``apt-get install`` command for the user to run and exit. The
# venv side (uv pip) is fully automated; the system side is opt-in by
# the user so setup never escalates privileges on their behalf.
check_system_deps() {
    if ! $WITH_RTP; then
        return 0
    fi
    if ! command -v apt-get >/dev/null 2>&1; then
        return 0  # not Debian/Ubuntu — user is on their own
    fi

    local pkgs=()
    # PyGObject lives in the venv (installed via uv below). What apt
    # owns here is purely non-Python:
    #   * C build deps for the source build (libcairo / libgirepository /
    #     pkg-config). uv-managed Python ships its own headers.
    #   * Runtime Gst typelib (PyGObject loads it via gobject-introspection).
    #   * gst-inspect-1.0 for the plugin-presence probe below.
    command -v pkg-config >/dev/null 2>&1                       || pkgs+=(pkg-config)
    pkg-config --exists cairo 2>/dev/null                       || pkgs+=(libcairo2-dev)
    # Debian's libgirepository1.0-dev publishes the .pc file as
    # gobject-introspection-1.0, NOT girepository-1.0 — probe accordingly.
    pkg-config --exists gobject-introspection-1.0 2>/dev/null   || pkgs+=(libgirepository1.0-dev)
    ls /usr/lib/*-linux-gnu/girepository-1.0/Gst-1.0.typelib >/dev/null 2>&1 \
                                                                || pkgs+=(gir1.2-gstreamer-1.0)
    command -v gst-inspect-1.0 >/dev/null 2>&1                  || pkgs+=(gstreamer1.0-tools)
    # GStreamer elements RtpH264Sender / RtpH264Receiver need at runtime.
    # Checked per-element via gst-inspect-1.0 so partially-provisioned
    # hosts (typelib present, plugins missing — a real failure mode) still
    # get flagged correctly.
    local need_base=false need_good=false need_bad=false need_ugly=false
    if command -v gst-inspect-1.0 >/dev/null 2>&1; then
        gst-inspect-1.0 videoconvert >/dev/null 2>&1 || need_base=true
        gst-inspect-1.0 rtph264pay   >/dev/null 2>&1 || need_good=true
        gst-inspect-1.0 udpsink      >/dev/null 2>&1 || need_good=true
        gst-inspect-1.0 h264parse    >/dev/null 2>&1 || need_bad=true
        # x264enc is the CPU fallback in GstNvH264Encoder's candidate list.
        gst-inspect-1.0 x264enc      >/dev/null 2>&1 || need_ugly=true
    else
        # No gst-inspect → flag everything; user installs gst-tools and re-runs.
        need_base=true; need_good=true; need_bad=true; need_ugly=true
    fi
    $need_base && pkgs+=(gstreamer1.0-plugins-base)
    $need_good && pkgs+=(gstreamer1.0-plugins-good)
    $need_bad  && pkgs+=(gstreamer1.0-plugins-bad gstreamer1.0-libav)
    $need_ugly && pkgs+=(gstreamer1.0-plugins-ugly)

    # cuda-nvrtc on Jetson — JetPack ships partial CUDA without it.
    # Desktop CUDA installer drops libnvrtc into /usr/local/cuda; if it's
    # missing there, the user needs to fix their CUDA install.
    # capture, not `find | grep -q`: find's non-zero on an unreadable /usr dir trips pipefail.
    if $JETSON && [[ -z "$(find /usr -name 'libnvrtc.so*' -print -quit 2>/dev/null)" ]]; then
        pkgs+=("cuda-nvrtc-${cuda_major}-${cuda_minor}")
    fi

    if [[ ${#pkgs[@]} -eq 0 ]]; then
        return 0
    fi

    cat >&2 <<EOF
_install_deps.sh: missing system packages required by camera_viz (RTP path):
  ${pkgs[*]}

The exact command:
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends ${pkgs[*]}

(--no-rtp skips the GStreamer-based RTP path entirely.)
EOF

    local ans=""
    if [[ -e /dev/tty ]]; then
        # NOTE: do NOT redirect stderr — ``read -p`` writes the prompt to
        # stderr, and we want the user to actually see it.
        read -r -p "Run those apt-get commands now? [y/N] " ans </dev/tty || ans=""
    fi
    case "${ans,,}" in
        y|yes)
            if ! sudo -n true 2>/dev/null; then
                echo "    sudo password required (one-time)"
            fi
            sudo apt-get update -qq
            sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${pkgs[@]}"
            ;;
        *)
            echo "_install_deps.sh: aborted. Install the listed packages and re-run." >&2
            exit 1
            ;;
    esac
}
check_system_deps

# JetPack ships versioned libs (libnvrtc.so.13) without the unversioned
# symlink + ld.so cache entry that desktop CUDA creates. cupy looks up
# ``libnvrtc.so`` and fails to resolve without these. Skipped on desktop
# where the CUDA installer already lays down the right symlinks.
check_cuda_symlinks() {
    if ! $JETSON; then
        return 0
    fi
    if [[ ! -d /usr/local/cuda/lib64 ]]; then
        return 0
    fi
    local lib64=/usr/local/cuda/lib64
    local cmds=()
    for stem in libnvrtc.so libnvrtc-builtins.so libcudart.so; do
        if [[ ! -e "$lib64/$stem" ]]; then
            local versioned
            versioned=$(ls "$lib64/$stem".[0-9]* 2>/dev/null | sort -V | tail -1)
            if [[ -n "$versioned" ]]; then
                cmds+=("sudo ln -sf $(basename "$versioned") $lib64/$stem")
            fi
        fi
    done
    if ! ldconfig -p 2>/dev/null | grep -q "$lib64"; then
        cmds+=("echo $lib64 | sudo tee /etc/ld.so.conf.d/zz-camera-viz-cuda.conf >/dev/null"
               "sudo ldconfig")
    fi
    if [[ ${#cmds[@]} -eq 0 ]]; then
        return 0
    fi

    {
        echo "_install_deps.sh: Jetson CUDA libs aren't wired into ld.so / unversioned"
        echo "symlinks are missing. cupy will fail to dlopen libnvrtc.so without these."
        echo "Exact commands:"
        for c in "${cmds[@]}"; do
            echo "  $c"
        done
    } >&2

    local ans=""
    if [[ -e /dev/tty ]]; then
        read -r -p "Run those now? [y/N] " ans </dev/tty || ans=""
    fi
    case "${ans,,}" in
        y|yes)
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
            ;;
        *)
            echo "_install_deps.sh: aborted. Run the listed commands and re-run setup." >&2
            exit 1
            ;;
    esac
}
check_cuda_symlinks

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

# isaacteleop comes from PyPI by default (the published wheel includes the
# viz module). --wheel <path> installs a locally built wheel instead — only
# needed when developing against an unreleased build (see the build-from-source
# docs). Sender-only deploys don't install isaacteleop at all.
ISAACTELEOP_PKG="isaacteleop"
if [[ "$MODE" == full && -n "$WHEEL" ]]; then
    [[ -f "$WHEEL" ]] || {
        echo "_install_deps.sh: --wheel '$WHEEL' not found." >&2
        exit 1
    }
    ISAACTELEOP_PKG="$WHEEL"
fi

echo "==> mode:   $MODE"
echo "==> venv:   $VENV_DIR"
echo "==> python: $PYTHON_VERSION"
[[ "$MODE" == full ]] && echo "==> isaacteleop: $ISAACTELEOP_PKG"

if [[ ! -d "$VENV_DIR" ]]; then
    # Strict venv isolation: no --system-site-packages. PyGObject + every
    # other Python dep is installed into the venv via uv below. Sender mode
    # still defaults to system python3 because Jetson images sometimes
    # don't have a uv-managed Python build for the JetPack arch+libc combo
    # — but the venv itself stays isolated.
    if [[ "$MODE" == sender ]]; then
        sys_py="$(command -v python3 || true)"
        [[ -x "$sys_py" ]] || {
            echo "_install_deps.sh: system python3 required in --sender-only mode" >&2
            exit 1
        }
        uv venv "$VENV_DIR" --python "$sys_py"
    else
        uv venv "$VENV_DIR" --python "$PYTHON_VERSION"
    fi
fi
PY="$VENV_DIR/bin/python"

echo "==> cuda:   ${cuda_major}.${cuda_minor} (cupy-cuda${cuda_major}x, cuda-nvrtc-${cuda_major}-${cuda_minor})"

# cupy ships separate packages per CUDA major (cupy-cuda12x, cupy-cuda13x...);
# they coexist on disk and CuPy warns about "multiple CuPy packages installed."
# If a prior setup picked a different major, uninstall the stale variant now.
target_cupy="cupy-cuda${cuda_major}x"
for v in cupy-cuda11x cupy-cuda12x cupy-cuda13x; do
    if [[ "$v" != "$target_cupy" ]] && uv pip show --python "$PY" "$v" >/dev/null 2>&1; then
        echo "==> removing stale $v (target is $target_cupy)"
        uv pip uninstall --python "$PY" "$v" >/dev/null
    fi
done

# Broken-install guard: if dist-info is present but `import cupy` fails
# (interrupted setup, manual `rm -rf cupy/`), uv treats the package as
# installed and won't reinstall on the regular install line.
if uv pip show --python "$PY" "$target_cupy" >/dev/null 2>&1 \
        && ! "$PY" -c "import cupy" >/dev/null 2>&1; then
    echo "==> $target_cupy metadata present but import fails — reinstalling"
    uv pip uninstall --python "$PY" "$target_cupy" >/dev/null
fi

# Mirrors pyproject.toml. PyGObject is pinned <3.52: 3.52 dropped the
# girepository-1.0 build path, and Ubuntu 22.04 only ships 1.0
# (libgirepository1.0-dev). 3.50.x supports both. Source-builds against
# the C deps installed in ensure_apt_deps(); pycairo is a transitive dep.
PKGS=("pyyaml>=6.0" "$target_cupy" "numpy>=1.23" "scipy>=1.15")
[[ "$MODE" == full ]] && PKGS=("$ISAACTELEOP_PKG" "${PKGS[@]}")
$WITH_V4L2 && PKGS+=("opencv-python>=4.5")
$WITH_OAKD && PKGS+=("depthai>=3.0")
$WITH_RTP  && PKGS+=("pybind11>=2.11" "PyGObject>=3.42,<3.52")

# Local wheels keep version ``1.3+local`` across rebuilds; uv's --upgrade
# no-ops on them. mtime probe forces a reinstall when the wheel's newer.
EXTRA_UV=()
if [[ "$MODE" == full && -f "$WHEEL" ]]; then
    wheel_mtime=$(stat -c %Y "$WHEEL" 2>/dev/null || echo 0)
    # Empty on a fresh venv; `|| true` keeps the no-match from aborting under pipefail+set -e.
    installed_dist=$(ls -d "$VENV_DIR"/lib/python*/site-packages/isaacteleop-*.dist-info 2>/dev/null | head -1 || true)
    if [[ -n "$installed_dist" ]]; then
        installed_mtime=$(stat -c %Y "$installed_dist" 2>/dev/null || echo 0)
        if (( wheel_mtime > installed_mtime )); then
            echo "==> wheel newer than installed copy — forcing reinstall of isaacteleop"
            EXTRA_UV+=(--reinstall-package isaacteleop)
        fi
    fi
fi

echo "==> installing: ${PKGS[*]}"
if (( ${#EXTRA_UV[@]} > 0 )); then
    uv pip install --python "$PY" --upgrade "${EXTRA_UV[@]}" "${PKGS[@]}"
else
    uv pip install --python "$PY" --upgrade "${PKGS[@]}"
fi

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

# Smoke imports. ``gi`` is in the list under RTP to confirm PyGObject
# built and installed cleanly into the venv.
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
