#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# HOST-side setup for the SENSING SG8A GMSL rig (two SHW5G modules) on an
# AGX Orin running JetPack 7.2.1 / L4T R39.2.1.
#
# Installing the vendor drivers and selecting the device-tree overlay are host
# operations; see setup_container.sh for the other half.
#
# There is NO per-boot step. The vendor install.sh copies userspace SIPL
# drivers, a DTBO and ISP tuning files, and that is all -- there are no kernel
# modules to insmod and no /dev/video* nodes to configure.
#
# Usage:
#   ./setup_host.sh [options]
#
# Options:
#   --pkg DIR          vendor driver package dir (default: autodetect, or $SENSING_PKG_DIR)
#   --install-drivers  run the vendor install.sh (SIPL drivers + DTBO + NITO); needs a reboot
#   --groups           add $USER to the i2c and gpio groups
#   --smoke-test       stream both sensors for a few seconds via nvsipl_camera
#   -y, --yes          assume yes for every prompt
#   -h, --help         this text

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "$SCRIPT_DIR/_common.sh"

PKG_DIR=""
INSTALL_DRIVERS=0
DO_GROUPS=ask
SMOKE_TEST=0
ASSUME_YES=0

usage() { sed -n '4,26p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; }

while (( $# )); do
    case "$1" in
        --pkg)             PKG_DIR="$2"; shift 2 ;;
        --install-drivers) INSTALL_DRIVERS=1; shift ;;
        --groups)          DO_GROUPS=yes; shift ;;
        --smoke-test)      SMOKE_TEST=1; shift ;;
        -y|--yes)          ASSUME_YES=1; shift ;;
        -h|--help)         usage; exit 0 ;;
        *) die "unknown argument: $1" "Run $0 --help" ;;
    esac
done
export ASSUME_YES

# --- Preconditions ----------------------------------------------------------
if in_container; then
    die "this script must run on the HOST, not inside a container." \
        "Open a host terminal and run: $SCRIPT_DIR/setup_host.sh
         Inside the container, run setup_container.sh instead."
fi
[[ "$(uname -m)" == "aarch64" ]] || die "this rig is Jetson-only (found $(uname -m) )."

[[ -n "$PKG_DIR" ]] || PKG_DIR="$(find_sensing_pkg)"
[[ -n "$PKG_DIR" && -f "$PKG_DIR/install.sh" ]] || die \
    "SENSING driver package not found." \
    "Obtain $SENSING_PKG_GLOB from SENSING,
         then re-run with --pkg /path/to/package (or set SENSING_PKG_DIR)."
PKG_DIR="$(cd "$PKG_DIR" && pwd)"

printf '%sSENSING host setup (SIPL)%s\n' "$C_BOLD" "$C_RESET"
info "package: $PKG_DIR"
info "config:  $SENSING_PLATFORM_CONFIG  ($SENSING_CONFIG_JSON_REL)"
info "L4T:     R$(l4t_release || echo unknown)"

SUDO_REASONS=()
[[ "$INSTALL_DRIVERS" -eq 0 ]] || SUDO_REASONS+=(
    "installing the vendor SIPL drivers, device-tree overlay and ISP tuning files")
[[ "$DO_GROUPS" == no ]] || SUDO_REASONS+=(
    "adding $USER to the i2c and gpio groups (you will be asked first)")
[[ "${#SUDO_REASONS[@]}" -eq 0 ]] || require_sudo "${SUDO_REASONS[@]}"

# --- 1. Vendor install.sh (first install only; needs a reboot) --------------
if [[ "$INSTALL_DRIVERS" -eq 1 ]]; then
    step "Installing vendor SIPL drivers, DTBO and ISP tuning"
    warn "This wipes $SIPL_DRV_DIR and overwrites /usr/lib/aarch64-linux-gnu/nvidia/libnvcamerahal.so."
    if confirm "Proceed with the vendor install.sh?"; then
        ( cd "$PKG_DIR" && sudo ./install.sh )
        ok "vendor artifacts installed"
        printf '\n%s%sReboot required.%s Select the overlay first:\n' "$C_YELLOW" "$C_BOLD" "$C_RESET"
        hint "sudo /opt/nvidia/jetson-io/jetson-io.py"
        hint "  Configure Jetson AGX CSI Connector"
        hint "  -> Configure for compatible hardware"
        hint "  -> $SENSING_OVERLAY_NAME"
        hint "  -> Save pin changes -> Save and reboot to reconfigure pins"
        printf '\nAfter the reboot, set maximum performance and re-run this script:\n'
        hint "sudo nvpmodel -m 0 && sudo jetson_clocks"
        exit 0
    fi
    warn "skipped vendor install.sh"
fi

# --- 2. Vendor artifacts in place -------------------------------------------
step "Vendor artifacts"
[[ -f /boot/tegra234-camera-sipl-camera-overlay.dtbo ]] \
    && ok "/boot/tegra234-camera-sipl-camera-overlay.dtbo" \
    || { bad "device-tree overlay not installed"; hint "Re-run with --install-drivers"; }
if compgen -G "$SIPL_DRV_DIR/libnvuddf_*" >/dev/null; then
    ok "$SIPL_DRV_DIR ($(find "$SIPL_DRV_DIR" -name 'libnv*' | wc -l) driver libs)"
else
    bad "$SIPL_DRV_DIR is empty"; hint "Re-run with --install-drivers"
fi
[[ -r "$SIPL_NITO_DIR/$SENSING_NITO" ]] \
    && ok "$SIPL_NITO_DIR/$SENSING_NITO" \
    || { bad "$SENSING_NITO missing — the ISP has no tuning to load"; hint "Re-run with --install-drivers"; }

# --- 3. Group membership ----------------------------------------------------
# SIPL needs no root, but it does need the groups owning the deserializer I2C
# buses and the GPIO chips that gate deserializer power.
step "Group membership"
mapfile -t MISSING_GIDS < <(sensing_missing_gids)
if [[ "${#MISSING_GIDS[@]}" -eq 0 ]]; then
    ok "$USER can already reach every node SIPL opens"
else
    names=()
    for gid in "${MISSING_GIDS[@]}"; do
        names+=("$(getent group "$gid" | cut -d: -f1 || echo "$gid")")
    done
    info "missing: ${names[*]}"
    add_groups=0
    case "$DO_GROUPS" in
        yes) add_groups=1 ;;
        no)  info "skipped" ;;
        ask) confirm "Add $USER to ${names[*]}?" && add_groups=1 ;;
    esac
    if [[ "$add_groups" -eq 1 ]]; then
        sudo usermod -aG "$(IFS=,; echo "${names[*]}")" "$USER"
        ok "added — log out and back in for it to take effect"
        warn "Group changes do not apply to this shell. Re-login before the smoke test."
    else
        warn "without these, SIPL fails with: Master SetPlatformConfig (Camera HAL) failed. status: 10"
    fi
fi

# --- 4. Performance mode ----------------------------------------------------
step "Performance mode"
if have nvpmodel; then
    mode="$(nvpmodel -q 2>/dev/null | sed -n 's/^NV Power Mode: //p' | head -1)"
    info "power mode: ${mode:-unknown}"
    hint "Two sensors at 2560x1984@60 want: sudo nvpmodel -m 0 && sudo jetson_clocks"
else
    info "nvpmodel not found"
fi

# --- 5. Optional smoke test -------------------------------------------------
# The honest overlay check. If the DTBO is not selected, or the modules are on
# the wrong ports, this is what says so.
if [[ "$SMOKE_TEST" -eq 1 ]]; then
    step "Vendor smoke test"
    if ! have nvsipl_camera; then
        bad "nvsipl_camera not on PATH — installed by the vendor install.sh"
    else
        info "streaming $SENSING_PLATFORM_CONFIG for 5s"
        ( cd "$PKG_DIR" && nvsipl_camera \
            -t "$SENSING_CONFIG_JSON_REL" -c "$SENSING_PLATFORM_CONFIG" \
            -m "$SENSING_LINK_MASKS" --enable-camera-hal -s -Z -r 5 ) \
            && ok "both sensors streamed" \
            || bad "smoke test failed — check cabling on CN1 CAM2/CAM3 and the selected overlay"
    fi
fi

step "Verifying"
"$SCRIPT_DIR/verify.sh" || true

printf '\n%s%sHost setup complete.%s\n' "$C_GREEN" "$C_BOLD" "$C_RESET"
printf 'Next: run %ssetup_container.sh%s inside the devcontainer.\n' "$C_BOLD" "$C_RESET"
