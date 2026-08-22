# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for the SENSING setup scripts. Sourced, never executed.

# Colour is opt-out (NO_COLOR) and auto-disabled when stdout is not a terminal,
# so piped/CI output stays greppable.
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[34m'; C_CYAN=$'\033[36m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_CYAN=''
fi

step() { printf '\n%s==>%s %s%s%s\n' "$C_BLUE$C_BOLD" "$C_RESET" "$C_BOLD" "$1" "$C_RESET"; }
ok()   { printf '  %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$1"; }
info() { printf '  %s·%s %s\n' "$C_DIM" "$C_RESET" "$1"; }
warn() { printf '  %s!%s %s\n' "$C_YELLOW$C_BOLD" "$C_RESET" "$1" >&2; }
bad()  { printf '  %s✗%s %s\n' "$C_RED$C_BOLD" "$C_RESET" "$1" >&2; }
hint() { printf '    %s%s%s\n' "$C_CYAN" "$1" "$C_RESET"; }

die() {
    printf '\n%sError:%s %s\n' "$C_RED$C_BOLD" "$C_RESET" "$1" >&2
    [[ -z "${2:-}" ]] || printf '%sAction:%s %s\n' "$C_CYAN$C_BOLD" "$C_RESET" "$2" >&2
    exit 1
}

have() { command -v "$1" >/dev/null 2>&1; }

in_container() {
    [[ -f /.dockerenv ]] || grep -qE '(docker|containerd|kubepods)' /proc/1/cgroup 2>/dev/null
}

# Loud, coloured notice naming every privileged action before the first prompt,
# then pre-authenticate so the password prompt lands here rather than midway
# through a driver load. `sudo -n true` first: on NOPASSWD hosts `sudo -v` still
# demands a password and would break unattended runs.
require_sudo() {
    local width=72 line reason

    # Full banner once per run; later privileged actions get a one-liner so the
    # notice stays visible without turning into wallpaper.
    if [[ "${_SUDO_BANNER_SHOWN:-0}" == "1" ]]; then
        for reason in "$@"; do
            printf '  %ssudo:%s %s\n' "$C_YELLOW$C_BOLD" "$C_RESET" "$reason"
        done
        sudo -n true 2>/dev/null && return 0
        sudo -v || die "sudo authentication failed." "Re-run as a user with sudo privileges."
        return 0
    fi
    _SUDO_BANNER_SHOWN=1

    printf -v line '%*s' "$width" ''; line=${line// /═}

    printf '\n%s%s╔%s╗%s\n' "$C_YELLOW" "$C_BOLD" "$line" "$C_RESET"
    printf '%s%s║%s SUDO REQUIRED %*s║%s\n' \
        "$C_YELLOW" "$C_BOLD" "$C_RED" "$((width - 15))" '' "$C_RESET"
    printf '%s%s╚%s╝%s\n' "$C_YELLOW" "$C_BOLD" "$line" "$C_RESET"
    printf '%sThis script needs root privileges for:%s\n' "$C_BOLD" "$C_RESET"
    local reason
    for reason in "$@"; do
        printf '  %s•%s %s\n' "$C_YELLOW$C_BOLD" "$C_RESET" "$reason"
    done
    printf '%sYou will be asked again before each optional action. Ctrl-C now to abort.%s\n\n' \
        "$C_DIM" "$C_RESET"

    if sudo -n true 2>/dev/null; then
        ok "sudo already authenticated"
        return 0
    fi
    printf '%sEnter your password to continue.%s\n' "$C_CYAN" "$C_RESET"
    sudo -v || die "sudo authentication failed." "Re-run as a user with sudo privileges."
}

# Yes/no prompt. ASSUME_YES=1 auto-accepts; a non-interactive stdin declines,
# so unattended runs never silently take a privileged optional action.
confirm() {
    local prompt="$1" reply
    if [[ "${ASSUME_YES:-0}" == "1" ]]; then
        info "$prompt ${C_DIM}[auto-yes]${C_RESET}"
        return 0
    fi
    if [[ ! -t 0 ]]; then
        warn "$prompt — declined (non-interactive; pass --yes to accept)"
        return 1
    fi
    printf '%s%s%s [y/N] ' "$C_YELLOW$C_BOLD" "$prompt" "$C_RESET"
    read -r reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

# ---------------------------------------------------------------------------
# Rig facts. Ports, resolutions and node ranges come from the vendor Readme.md;
# ARGUS_ID_* come from the /proc/device-tree/tegra-camera-platform/modules
# ordering, which is what Argus enumerates as sensor-id.
# ---------------------------------------------------------------------------
SENSING_PKG_GLOB='SG10A_AGON_G2M_A1_AGX_ORIN_S56Cx1_SHF3Lx6_JP6.2_L4TR36.4.3'
S56C_NODES=(0 1 2 3)       # J27 -> video0/1, J29 -> video2/3; RAW, 1920x1080
SHF3L_NODES=(4 5 6 7 8 9)  # J25 J26 J23 J24 J21 J22;          YUV, 1920x1536

# Locate the vendor driver package. $SENSING_PKG_DIR wins; otherwise search the
# usual drop points. Prints the path, empty if not found.
find_sensing_pkg() {
    if [[ -n "${SENSING_PKG_DIR:-}" ]]; then
        printf '%s\n' "$SENSING_PKG_DIR"
        return 0
    fi
    local d
    for d in "$HOME/Sensing/$SENSING_PKG_GLOB" \
             "$HOME/$SENSING_PKG_GLOB" \
             /home/*/Sensing/"$SENSING_PKG_GLOB" \
             /home/*/"$SENSING_PKG_GLOB" \
             /opt/sensing/"$SENSING_PKG_GLOB"; do
        [[ -f "$d/load_modules.sh" ]] && { printf '%s\n' "$d"; return 0; }
    done
    printf '\n'
}

# Locate Argus/Argus.h. The apt package puts it under /usr/src; containers
# rarely have the L4T apt repo, so a copy of the jetson_multimedia_api argus
# tree next to the driver package is accepted too. Prints the include dir.
find_argus_include() {
    local d
    for d in "${ARGUS_INCLUDE_DIR:-}" \
             /usr/src/jetson_multimedia_api/argus/include \
             /usr/src/jetson_multimedia_api/include \
             "$HOME/Sensing/argus/include" \
             /usr/local/src/argus/include; do
        [[ -n "$d" && -f "$d/Argus/Argus.h" ]] && { printf '%s\n' "$d"; return 0; }
    done
    return 1
}

# Video nodes that currently exist, as bare indices.
sensing_video_nodes() {
    local dev
    for dev in /dev/video*; do
        [[ -e "$dev" ]] && printf '%s\n' "${dev#/dev/video}"
    done
}
