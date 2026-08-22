#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# HOST-side setup for the SENSING SG10A GMSL rig (Astra S56C + SHF3L) on an
# AGX Orin running JetPack 6.2 / L4T R36.4.3.
#
# Kernel modules, device-tree overlays and PWM/POC register writes only exist on
# the host, so this must not run in a container — see setup_container.sh for the
# other half.
#
# Usage:
#   ./setup_host.sh [options]
#
# Options:
#   --pkg DIR          vendor driver package dir (default: autodetect, or $SENSING_PKG_DIR)
#   --fps N            trigger PWM frame rate: 10|15|20|30|60 (default 30)
#   --free-run         force trig_mode=0 on every sensor (default)
#   --trigger-sync     keep the vendor trigger mode; needs the J19 pin 2<->4 strap
#   --install-drivers  also run the vendor install.sh (Image + DTBO + ISP); needs a reboot
#   --service          install and enable the boot-time loader unit without asking
#   --no-service       never touch systemd
#   -y, --yes          assume yes for every prompt
#   -h, --help         this text

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "$SCRIPT_DIR/_common.sh"

PKG_DIR=""
FPS=30
FREE_RUN=1
INSTALL_DRIVERS=0
SERVICE_MODE=ask
ASSUME_YES=0
SERVICE_NAME=sensing-camera
SERVICE_TEMPLATE="$SCRIPT_DIR/scripts/${SERVICE_NAME}.service.in"

usage() { sed -n '4,25p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; }

while (( $# )); do
    case "$1" in
        --pkg)             PKG_DIR="$2"; shift 2 ;;
        --fps)             FPS="$2"; shift 2 ;;
        --free-run)        FREE_RUN=1; shift ;;
        --trigger-sync)    FREE_RUN=0; shift ;;
        --install-drivers) INSTALL_DRIVERS=1; shift ;;
        --service)         SERVICE_MODE=yes; shift ;;
        --no-service)      SERVICE_MODE=no; shift ;;
        -y|--yes)          ASSUME_YES=1; shift ;;
        -h|--help)         usage; exit 0 ;;
        *) die "unknown argument: $1" "Run $0 --help" ;;
    esac
done
export ASSUME_YES

case "$FPS" in 10|15|20|30|60) ;; *) die "--fps must be one of 10 15 20 30 60 (got '$FPS')" ;; esac

# --- Preconditions ----------------------------------------------------------
if in_container; then
    die "this script must run on the HOST, not inside a container." \
        "Open a host terminal and run: $SCRIPT_DIR/setup_host.sh
         Inside the container, run setup_container.sh instead."
fi
[[ "$(uname -m)" == "aarch64" ]] || die "this rig is Jetson-only (found $(uname -m) )."

[[ -n "$PKG_DIR" ]] || PKG_DIR="$(find_sensing_pkg)"
[[ -n "$PKG_DIR" && -f "$PKG_DIR/load_modules.sh" ]] || die \
    "SENSING driver package not found." \
    "Download $SENSING_PKG_GLOB from
         https://github.com/SENSING-Technology/nvidia-jetson-camera-drivers
         then re-run with --pkg /path/to/package (or set SENSING_PKG_DIR)."
PKG_DIR="$(cd "$PKG_DIR" && pwd)"

printf '%sSENSING host setup%s\n' "$C_BOLD" "$C_RESET"
info "package: $PKG_DIR"
info "trigger: $([[ "$FREE_RUN" -eq 1 ]] && echo "free run (trig_mode=0)" || echo "vendor sync @ ${FPS} Hz")"

SUDO_REASONS=(
    "insmod the SENSING sensor drivers (s56c-shw3gc.ko, sgx-yuv-gmsl2.ko, pwm-gpio.ko)"
    "devmem writes that enable camera power-over-coax and the PWM trigger pin"
    "restarting nvargus-daemon so Argus re-enumerates the sensors"
)
[[ "$INSTALL_DRIVERS" -eq 0 ]] || SUDO_REASONS+=(
    "installing the vendor kernel Image, device-tree overlay and ISP tuning file")
[[ "$SERVICE_MODE" == no ]] || SUDO_REASONS+=(
    "writing /etc/systemd/system/${SERVICE_NAME}.service (you will be asked first)")
[[ "$(command -v v4l2-ctl)" ]] || SUDO_REASONS+=("apt-get install v4l-utils")
require_sudo "${SUDO_REASONS[@]}"

# --- 1. Vendor install.sh (optional; needs a reboot) ------------------------
if [[ "$INSTALL_DRIVERS" -eq 1 ]]; then
    step "Installing vendor kernel Image, DTBO and ISP tuning"
    warn "This overwrites /boot/Image and wipes /var/nvidia/nvcam/settings/."
    if confirm "Proceed with the vendor install.sh?"; then
        ( cd "$PKG_DIR" && sudo ./install.sh )
        ok "vendor artifacts installed"
        printf '\n%s%sReboot required.%s Select the overlay first:\n' "$C_YELLOW" "$C_BOLD" "$C_RESET"
        hint "sudo /opt/nvidia/jetson-io/jetson-io.py"
        hint "  Configure Jetson AGX CSI Connector"
        hint "  -> Jetson Sensing SG10A_AGON_G2M_A1 S56Cx1 SHF3Lx6 -> Save and reboot"
        printf 'Re-run this script (without --install-drivers) after the reboot.\n'
        exit 0
    fi
    warn "skipped vendor install.sh"
fi

# --- 2. Overlay must already be live ---------------------------------------
step "Checking the live device tree"
DT_MODULES=/proc/device-tree/tegra-camera-platform/modules
[[ -d "$DT_MODULES" ]] || die \
    "the SENSING device-tree overlay is not applied." \
    "Run: $0 --install-drivers   then select the overlay in jetson-io and reboot."
ok "overlay applied ($(find "$DT_MODULES" -mindepth 1 -maxdepth 1 -name 'module*' | wc -l) camera modules)"

# --- 3. Load the sensor drivers --------------------------------------------
# install.sh never copies the sensor .ko files into /lib/modules, so nothing
# auto-loads them. This is the step that has to happen on every boot.
step "Loading sensor drivers (${FPS} Hz trigger)"
have v4l2-ctl || sudo apt-get install -y v4l-utils
LOADER="$SCRIPT_DIR/scripts/sensing-load.sh"
[[ -x "$LOADER" ]] || die "loader not found or not executable: $LOADER"

LOADER_ARGS=(--pkg "$PKG_DIR" --fps "$FPS" --restart-argus)
[[ "$FREE_RUN" -eq 0 ]] || LOADER_ARGS+=(--free-run)
sudo "$LOADER" "${LOADER_ARGS[@]}"

mapfile -t NODES < <(sensing_video_nodes)
[[ "${#NODES[@]}" -gt 0 ]] || die \
    "drivers loaded but no /dev/video* nodes appeared." \
    "Check camera power and cabling, then: sudo dmesg | grep -iE 's56|sgx|max96'"
ok "${#NODES[@]} video node(s): $(printf 'video%s ' "${NODES[@]}")"

if [[ "$FREE_RUN" -eq 0 ]]; then
    warn "Sensors are slaved to the PWM trigger. Without the J19 pin 2<->4 strap they will never deliver a frame."
fi

for _ in $(seq 1 20); do [[ -S /tmp/argus_socket ]] && break; sleep 0.25; done
[[ -S /tmp/argus_socket ]] && ok "/tmp/argus_socket ready" \
    || warn "/tmp/argus_socket did not appear — check: systemctl status nvargus-daemon"

# --- 6. Persist across reboots ---------------------------------------------
install_service=0
case "$SERVICE_MODE" in
    yes) install_service=1 ;;
    no)  info "systemd unit skipped (--no-service)" ;;
    ask)
        step "Persisting the driver load across reboots"
        info "Without this, /dev/video* disappears on every reboot until load_modules.sh is re-run."
        confirm "Install and enable ${SERVICE_NAME}.service?" && install_service=1
        ;;
esac

if [[ "$install_service" -eq 1 ]]; then
    [[ -f "$SERVICE_TEMPLATE" ]] || die "service template missing: $SERVICE_TEMPLATE"
    unit="/etc/systemd/system/${SERVICE_NAME}.service"
    free_run_flag=""
    [[ "$FREE_RUN" -eq 0 ]] || free_run_flag=" --free-run"
    sed -e "s|{{LOADER}}|$LOADER|g" \
        -e "s|{{PKG_DIR}}|$PKG_DIR|g" \
        -e "s|{{FPS}}|$FPS|g" \
        -e "s|{{FREE_RUN}}|$free_run_flag|g" \
        "$SERVICE_TEMPLATE" | sudo tee "$unit" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}.service"
    ok "installed and enabled $unit"
fi

step "Verifying"
"$SCRIPT_DIR/verify.sh" || true

printf '\n%s%sHost setup complete.%s\n' "$C_GREEN" "$C_BOLD" "$C_RESET"
printf 'Next: run %ssetup_container.sh%s inside the devcontainer.\n' "$C_BOLD" "$C_RESET"
