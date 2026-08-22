#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# CONTAINER-side setup for the SENSING SG10A rig.
#
# The drivers themselves live in the host kernel — this half only wires up what
# a container needs to *consume* them: the Argus client socket, v4l-utils, and
# the headers the camera_viz Argus source builds against.
#
# Usage:
#   ./setup_container.sh [options]
#
# Options:
#   --build-argus       build the camera_viz native Argus module (needs an active venv)
#   --argus-include D   Argus header dir, if it is not in a standard location
#   -y, --yes           assume yes for every prompt
#   -h, --help          this text

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# shellcheck source=./_common.sh
source "$SCRIPT_DIR/_common.sh"

BUILD_ARGUS=0
ASSUME_YES=0

usage() { sed -n '4,18p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; }

while (( $# )); do
    case "$1" in
        --build-argus)   BUILD_ARGUS=1; shift ;;
        --argus-include) ARGUS_INCLUDE_DIR="$2"; export ARGUS_INCLUDE_DIR; shift 2 ;;
        -y|--yes)        ASSUME_YES=1; shift ;;
        -h|--help)       usage; exit 0 ;;
        *) die "unknown argument: $1" "Run $0 --help" ;;
    esac
done
export ASSUME_YES

in_container || die "this script is for the CONTAINER side." \
    "You appear to be on the host — run setup_host.sh instead."

printf '%sSENSING container setup%s\n' "$C_BOLD" "$C_RESET"

BLOCKED=0

# --- 1. Video nodes ---------------------------------------------------------
# Driver loading is a host-kernel operation; nothing here can fix its absence.
step "Video nodes from the host"
mapfile -t NODES < <(sensing_video_nodes)
if [[ "${#NODES[@]}" -gt 0 ]]; then
    ok "${#NODES[@]} node(s) visible: $(printf 'video%s ' "${NODES[@]}")"
else
    bad "no /dev/video* visible in this container"
    hint "On the HOST:  $REPO_ROOT/src/plugins/sensing/setup_host.sh"
    hint "If the host has them but this container does not, the container needs --device /dev or -v /dev:/dev"
    BLOCKED=1
fi

# --- 2. Argus socket --------------------------------------------------------
# libnvargus_socketclient talks to nvargus-daemon over this UNIX socket. A
# container that bind-mounts /tmp/.X11-unix still gets its own /tmp, so the
# socket has to be mounted explicitly.
step "Argus daemon socket"
if [[ -S /tmp/argus_socket ]]; then
    ok "/tmp/argus_socket present"
else
    bad "/tmp/argus_socket is not visible in this container"
    hint "Argus capture (and argus_camera) cannot connect without it."
    printf '\n    %sdocker run:%s add\n' "$C_BOLD" "$C_RESET"
    hint '  -v /tmp/argus_socket:/tmp/argus_socket'
    printf '    %sdevcontainer.json:%s add to "runArgs", next to the X11 mount\n' "$C_BOLD" "$C_RESET"
    hint '  "-v", "/tmp/argus_socket:/tmp/argus_socket"'
    printf '    then rebuild the container. On the host, confirm the socket exists:\n'
    hint '  ls -l /tmp/argus_socket || sudo systemctl restart nvargus-daemon'
    BLOCKED=1
fi

# --- 3. v4l-utils -----------------------------------------------------------
step "v4l-utils"
if have v4l2-ctl; then
    ok "v4l2-ctl present"
else
    info "v4l2-ctl is needed to read/set trig_mode and sensor_mode."
    require_sudo "apt-get install v4l-utils inside this container"
    if confirm "Install v4l-utils now?"; then
        sudo apt-get update -qq && sudo apt-get install -y v4l-utils
        ok "v4l-utils installed"
    else
        warn "skipped — trig_mode checks will be unavailable"
    fi
fi

# --- 4. Argus build prerequisites ------------------------------------------
# Both camera_viz/argus/build.sh and camera_viz/scripts/_install_deps.sh hardcode
# /usr/src/jetson_multimedia_api/argus — build.sh does not forward an override to
# CMake, and _install_deps.sh skips the build outright when that path is absent.
# So a header tree found anywhere else gets symlinked into place rather than
# passed as a flag.
JMA_ARGUS=/usr/src/jetson_multimedia_api/argus
step "Argus build prerequisites"
if ARGUS_INC="$(find_argus_include)"; then
    ok "headers: $ARGUS_INC"
    if [[ ! -d "$JMA_ARGUS" ]]; then
        argus_tree="$(dirname "$ARGUS_INC")"
        warn "camera_viz expects them at $JMA_ARGUS"
        require_sudo "symlink $JMA_ARGUS -> $argus_tree"
        if confirm "Create that symlink?"; then
            sudo mkdir -p "$(dirname "$JMA_ARGUS")"
            sudo ln -sfn "$argus_tree" "$JMA_ARGUS"
            ok "linked $JMA_ARGUS -> $argus_tree"
        else
            warn "declined — 'camera_viz.sh setup --with-argus' will skip the Argus build"
        fi
    fi
else
    ARGUS_INC=""
    bad "Argus/Argus.h not found"
    hint "Containers rarely carry the L4T apt repo, so nvidia-l4t-jetson-multimedia-api"
    hint "is usually not installable here. Either mount the host copy:"
    hint "  -v /usr/src/jetson_multimedia_api:/usr/src/jetson_multimedia_api:ro"
    hint "or copy that tree in and pass --argus-include <dir>/argus/include"
fi

if find /usr/lib -maxdepth 3 -name 'libnvargus_socketclient.so*' 2>/dev/null | grep -q .; then
    ok "libnvargus_socketclient.so present"
else
    bad "libnvargus_socketclient.so not found — the NVIDIA container runtime should provide it"
    BLOCKED=1
fi
[[ -f /usr/include/EGL/egl.h ]] && ok "EGL headers present" \
    || { bad "EGL headers missing"; hint "sudo apt-get install -y libegl1-mesa-dev"; }
if have nvcc || [[ -x /usr/local/cuda/bin/nvcc ]]; then
    ok "nvcc: $("${CUDA_PATH:-/usr/local/cuda}/bin/nvcc" --version 2>/dev/null | sed -n 's/.*release \([0-9.]*\).*/CUDA \1/p' | tail -1)"
else
    bad "nvcc not found"; hint "Expected at /usr/local/cuda/bin/nvcc"
fi

# --- 5. Native Argus module -------------------------------------------------
# examples/camera_viz/argus/ arrives with the Argus camera source (PR #833).
# Absent it, camera_viz can still drive the YUV SHF3L nodes via type: v4l2.
ARGUS_SRC="$REPO_ROOT/examples/camera_viz/argus"
step "camera_viz native Argus module"
if [[ ! -d "$ARGUS_SRC" ]]; then
    info "examples/camera_viz/argus not in this checkout — 'type: argus' unavailable."
    hint "It lands with the Argus camera support PR; until then use 'type: v4l2' for the SHF3L nodes."
elif [[ "$BUILD_ARGUS" -eq 0 ]]; then
    info "present but not built (pass --build-argus)"
elif [[ -z "$ARGUS_INC" ]]; then
    bad "cannot build without Argus headers — see above"
    BLOCKED=1
elif [[ -z "${VIRTUAL_ENV:-}" ]]; then
    bad "no active venv; build.sh requires one"
    hint "source $REPO_ROOT/examples/camera_viz/.venv/bin/activate"
    BLOCKED=1
else
    info "building against $ARGUS_INC"
    "$ARGUS_SRC/build.sh" \
        && ok "native Argus module built" \
        || { bad "build failed"; BLOCKED=1; }
fi

# --- 6. argus_camera on PATH ------------------------------------------------
# The vendor's smoke test. /usr/local/bin is container-local, so a copy the host
# installed there is invisible here; a build in the mounted home is not.
step "argus_camera"
if have argus_camera; then
    ok "argus_camera on PATH"
else
    # The Argus sample tree nests it at argus/build/apps/camera/ui/camera/, so
    # search deep — but only under likely roots, not all of $HOME.
    found="$(find "$HOME/Sensing" "$REPO_ROOT" /usr/local/bin \
        -maxdepth 9 -type f -name argus_camera -perm -u+x 2>/dev/null | head -1)"
    if [[ -n "$found" ]]; then
        info "not on PATH, but built at: $found"
        if confirm "Symlink it into ~/.local/bin?"; then
            mkdir -p "$HOME/.local/bin" && ln -sf "$found" "$HOME/.local/bin/argus_camera"
            ok "linked ~/.local/bin/argus_camera"
        fi
    else
        info "not built in this container — optional, only a smoke-test tool"
        hint "Build it from the jetson_multimedia_api argus tree, or run it on the host."
    fi
fi

step "Verifying"
"$SCRIPT_DIR/verify.sh" || true

printf '\n'
if [[ "$BLOCKED" -eq 0 ]]; then
    printf '%s%sContainer setup complete.%s\n' "$C_GREEN" "$C_BOLD" "$C_RESET"
else
    printf '%s%sContainer setup incomplete — see the actions above.%s\n' "$C_YELLOW" "$C_BOLD" "$C_RESET"
fi
