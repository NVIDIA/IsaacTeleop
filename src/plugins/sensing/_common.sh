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

# ---------------------------------------------------------------------------
# Download cache
#
# The SDK artifacts total ~73 MB and are re-fetched on every container rebuild,
# because /usr/src does not survive one. The cache does: it lives in the
# worktree, which is bind-mounted from the host. Gitignored.
# ---------------------------------------------------------------------------
_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SENSING_CACHE_DIR="${SENSING_CACHE_DIR:-$_COMMON_DIR/.cache}"

# fetch_cached URL VALIDATOR -> sets FETCHED_PATH
#
# Filenames are version-stamped, so the basename is the cache key and a new BSP
# fetches a new file rather than invalidating this one. VALIDATOR is a command
# run on the path; a cached file that fails it is re-fetched, so a truncated or
# half-written download cannot poison a later build.
FETCHED_PATH=""
fetch_cached() {
    local url="$1" validate="$2"
    local name path tmp
    name="$(basename "$url")"
    path="$SENSING_CACHE_DIR/$name"
    FETCHED_PATH=""

    if [[ -f "$path" ]]; then
        if "$validate" "$path" >/dev/null 2>&1; then
            ok "cached: $name ($(du -h "$path" | cut -f1))"
            FETCHED_PATH="$path"
            return 0
        fi
        warn "cached $name failed validation — re-fetching"
        rm -f "$path"
    fi

    mkdir -p "$SENSING_CACHE_DIR" || return 1
    # Download to .part and rename, so an interrupted fetch never leaves a
    # plausible-looking cache entry behind.
    tmp="$path.part"
    info "downloading $name"
    # A bar on a terminal, silence when piped -- curl's default meter is three
    # lines of carriage-return noise in a log.
    local progress=(--progress-bar); [[ -t 1 ]] || progress=(-sS)
    curl -fL "${progress[@]}" --retry 3 "$url" -o "$tmp" || { rm -f "$tmp"; return 1; }
    if ! "$validate" "$tmp" >/dev/null 2>&1; then
        rm -f "$tmp"
        return 1
    fi
    mv -f "$tmp" "$path"
    ok "cached: $name ($(du -h "$path" | cut -f1))"
    FETCHED_PATH="$path"
}

# Validators for fetch_cached. Cheap structural checks -- NVIDIA publishes no
# checksums for these artifacts, so "is it the right kind of archive" is as far
# as verification goes.
valid_deb()  { dpkg-deb --info "$1"; }
valid_tbz2() { tar tjf "$1"; }

in_container() {
    [[ -f /.dockerenv ]] || grep -qE '(docker|containerd|kubepods)' /proc/1/cgroup 2>/dev/null
}

# Loud, coloured notice naming every privileged action before the first prompt,
# then pre-authenticate so the password prompt lands here rather than midway
# through an install. `sudo -n true` first: on NOPASSWD hosts `sudo -v` still
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
# Rig facts
#
# SENSING SG8A-AGON-G2Y-A1 carrier, two SHW5G modules on CN1 CAM2/CAM3, driven
# through SIPL. There are no kernel sensor drivers and no /dev/video* nodes:
# SIPL owns the sensors from userspace. Everything below is read off the vendor
# platform config, not guessed -- run `nvsipl_query -t <json> -c <config>` to
# re-derive it.
# ---------------------------------------------------------------------------
SENSING_PKG_GLOB='SG8A_AGON_G2Y_A1_AGX_ORIN_S56C_SHW5G_SHF3L_SIPL_JP7.2.1_L4TR39.2.1'
SENSING_CONFIG_JSON_REL='query/sg8a_agth_g2a/shw5g.json'
SENSING_PLATFORM_CONFIG='SHW5G_2'
# One mask per deserializer, in transport order: nothing on CSI-GH, links 2 and
# 3 on CSI-CD.
SENSING_LINK_MASKS='0x0000 0x1100'
SENSING_NITO='SHW5G.nito'
SENSING_OVERLAY_NAME='Jetson Sensing SG8A-AGON-G2Y-A1 SIPL GMSL2x8'

# The two MAX96712 deserializer buses, from `i2cDevice` in the platform config.
SENSING_I2C_BUSES=(9 10)

SIPL_DRV_DIR=/usr/lib/nvsipl_drv
SIPL_NITO_DIR=/var/nvidia/nvcam/settings/sipl
SIPL_API_DIR="${SIPL_API_DIR:-/usr/src/jetson_sipl_api}"
MMAPI_DIR="${MMAPI_DIR:-/usr/src/jetson_multimedia_api}"

# BSP version as it appears in the apt pool, e.g. 39.2.1-20260806224157.
# Parsed rather than hardcoded so the SDK fetch is version-matched by
# construction: "# R39 (release), REVISION: 2.1, ... DATE: ..." plus the
# matching pool timestamp is not derivable, so only MAJOR.MINOR is returned and
# the caller resolves the full version from the pool index.
l4t_release() {
    local rel
    [[ -r /etc/nv_tegra_release ]] || return 1
    rel="$(sed -n '1s/^# R\([0-9]*\).*REVISION: \([0-9.]*\).*/\1.\2/p' /etc/nv_tegra_release)"
    [[ -n "$rel" ]] || return 1
    printf '%s\n' "$rel"
}

# Locate the vendor driver package. $SENSING_PKG_DIR wins; otherwise search the
# usual drop points. Prints the path, empty if not found.
#
# Identified by install.sh + the query/ tree, since the SIPL package has no
# load_modules.sh -- there is nothing to load.
find_sensing_pkg() {
    if [[ -n "${SENSING_PKG_DIR:-}" ]]; then
        printf '%s\n' "$SENSING_PKG_DIR"
        return 0
    fi
    local d
    for d in "$HOME/$SENSING_PKG_GLOB" \
             "$HOME/Sensing/$SENSING_PKG_GLOB" \
             /home/*/"$SENSING_PKG_GLOB" \
             /home/*/Sensing/"$SENSING_PKG_GLOB" \
             /opt/sensing/"$SENSING_PKG_GLOB"; do
        [[ -f "$d/install.sh" && -d "$d/query" ]] && { printf '%s\n' "$d"; return 0; }
    done
    printf '\n'
}

# SIPL API headers (jetson_sipl_api.tbz2). Prints the include root.
find_sipl_api() {
    local d
    for d in "$SIPL_API_DIR" /usr/src/jetson_sipl_api /opt/nvidia/jetson_sipl_api; do
        [[ -f "$d/sipl/include/NvSIPLCamera.hpp" ]] && { printf '%s\n' "$d"; return 0; }
    done
    return 1
}

# Jetson Multimedia API tree -- NvVideoEncoder sources and nvbufsurface.h.
find_mmapi() {
    local d
    for d in "$MMAPI_DIR" /usr/src/jetson_multimedia_api; do
        [[ -f "$d/include/NvVideoEncoder.h" ]] && { printf '%s\n' "$d"; return 0; }
    done
    return 1
}

# Device nodes SIPL opens, as "path:description" pairs. Readability of each is
# the whole container-side health check: everything here is 0660 root:<group>,
# so a missing supplementary group is the only realistic failure.
sensing_required_nodes() {
    local bus
    for bus in "${SENSING_I2C_BUSES[@]}"; do
        printf '/dev/i2c-%s:MAX96712 deserializer bus\n' "$bus"
    done
    printf '/dev/gpiochip0:deserializer power enable\n'
    printf '/dev/gpiochip1:deserializer power enable\n'
    printf '/dev/capture-vi-channel0:VI capture channel\n'
    printf '/dev/capture-isp-channel0:ISP channel\n'
    printf '/dev/nvhost-ctrl-isp:ISP control\n'
    printf '/dev/nvmap:GPU memory\n'
    printf '/dev/v4l2-nvenc:H.264 encoder\n'
}

# GIDs of nodes this user cannot read, deduplicated. Empty output means the
# process can reach everything SIPL needs.
sensing_missing_gids() {
    local entry path gid seen=""
    while IFS= read -r entry; do
        path="${entry%%:*}"
        [[ -e "$path" ]] || continue
        [[ -r "$path" ]] && continue
        gid="$(stat -c %g "$path" 2>/dev/null)" || continue
        [[ " $seen " == *" $gid "* ]] && continue
        seen="$seen $gid"
        printf '%s\n' "$gid"
    done < <(sensing_required_nodes)
}
