#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Health report for the SENSING GMSL rig. Read-only, no sudo, safe to run from
# the host or from inside a container — it reports what the current context can
# actually see and names the script that fixes each gap.
#
# Exit: 0 all good, 1 something is broken.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "$SCRIPT_DIR/_common.sh"

FAILED=0
fail() { bad "$1"; [[ -z "${2:-}" ]] || hint "$2"; FAILED=1; }

usage() { sed -n '4,9p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; }
[[ "${1:-}" != "--help" && "${1:-}" != "-h" ]] || { usage; exit 0; }

if in_container; then CONTEXT=container; else CONTEXT=host; fi
printf '%sSENSING rig report%s  %s(context: %s)%s\n' \
    "$C_BOLD" "$C_RESET" "$C_DIM" "$CONTEXT" "$C_RESET"

# --- Platform ---------------------------------------------------------------
step "Platform"
KERNEL="$(uname -r)"
if [[ -r /etc/nv_tegra_release ]]; then
    ok "L4T: $(sed -n '1s/^# //p' /etc/nv_tegra_release)"
else
    warn "/etc/nv_tegra_release not readable — cannot confirm the L4T release"
fi
# The vendor package ships prebuilt .ko files for exactly this kernel; a
# mismatch means insmod will fail with "invalid module format".
if [[ "$KERNEL" == "5.15.148-tegra" ]]; then
    ok "kernel: $KERNEL"
else
    fail "kernel is $KERNEL, package .ko files are built for 5.15.148-tegra" \
        "Reflash to JetPack 6.2 / L4T R36.4.3, or get a package matching this kernel."
fi

# --- Device tree ------------------------------------------------------------
step "Device tree overlay"
DT_MODULES=/proc/device-tree/tegra-camera-platform/modules
if [[ -d "$DT_MODULES" ]]; then
    n_modules="$(find "$DT_MODULES" -mindepth 1 -maxdepth 1 -name 'module*' | wc -l)"
    if [[ "$n_modules" -ge 10 ]]; then
        ok "overlay applied — $n_modules camera modules in the live tree"
    else
        fail "only $n_modules camera modules in the live tree (expected 10)" \
            "The wrong DTBO is selected. Run: sudo /opt/nvidia/jetson-io/jetson-io.py"
    fi
else
    fail "no tegra-camera-platform modules in the live device tree" \
        "Run setup_host.sh --install-drivers, then select the overlay in jetson-io and reboot."
fi

# --- Sensor drivers ---------------------------------------------------------
# The vendor install.sh never copies these into /lib/modules, so nothing
# auto-loads them; load_modules.sh insmods them from the package directory.
step "Sensor drivers"
for mod in s56c_shw3gc sgx_yuv_gmsl2; do
    if grep -q "^${mod} " /proc/modules 2>/dev/null; then
        ok "$mod loaded"
    else
        fail "$mod not loaded" "Run setup_host.sh on the HOST (not in a container)."
    fi
done
for drv in s56-shw3g sgx-yuv-gmsl2; do
    if [[ -d "/sys/bus/i2c/drivers/$drv" ]]; then
        n_bound="$(find "/sys/bus/i2c/drivers/$drv" -maxdepth 1 -name '*-00*' | wc -l)"
        [[ "$n_bound" -gt 0 ]] \
            && ok "$drv bound to $n_bound i2c device(s)" \
            || warn "$drv registered but bound to nothing — check camera power and cabling"
    fi
done

# --- Video nodes ------------------------------------------------------------
step "Video nodes"
mapfile -t NODES < <(sensing_video_nodes)
if [[ "${#NODES[@]}" -eq 0 ]]; then
    fail "no /dev/video* nodes" "Run setup_host.sh on the HOST to load the drivers."
else
    ok "${#NODES[@]} node(s): $(printf 'video%s ' "${NODES[@]}")"
    for want in "${S56C_NODES[@]}"; do
        [[ -e "/dev/video$want" ]] || info "video$want (S56C) absent — normal if that port is empty"
    done
    for want in "${SHF3L_NODES[@]}"; do
        [[ -e "/dev/video$want" ]] || info "video$want (SHF3L) absent — normal if that port is empty"
    done
fi

# --- Trigger mode -----------------------------------------------------------
# load_modules.sh leaves the sensors slaved to the PWM trigger, which only
# fires when J19 pins 2 and 4 are strapped. Unstrapped, a sensor in that mode
# opens fine and then never delivers a frame — so flag it rather than let it
# look healthy.
step "Trigger mode"
if ! have v4l2-ctl; then
    warn "v4l2-ctl not installed — cannot read trig_mode"
    hint "sudo apt-get install -y v4l-utils   (or run setup_container.sh)"
elif [[ "${#NODES[@]}" -gt 0 ]]; then
    synced=0
    for i in "${NODES[@]}"; do
        tm="$(v4l2-ctl -d "/dev/video$i" -C trig_mode 2>/dev/null | sed -n 's/^trig_mode:[[:space:]]*//p')"
        case "$tm" in
            0)  ok  "video$i trig_mode=0 (free run)" ;;
            "") info "video$i has no trig_mode control" ;;
            *)  warn "video$i trig_mode=$tm (external trigger)"; synced=1 ;;
        esac
    done
    [[ "$synced" -eq 0 ]] || hint "No J19 pin 2<->4 strap? These will never produce a frame. Fix: setup_host.sh --free-run"
fi

# --- Argus ------------------------------------------------------------------
step "Argus"
if [[ -S /tmp/argus_socket ]]; then
    ok "/tmp/argus_socket present"
else
    if [[ "$CONTEXT" == container ]]; then
        fail "/tmp/argus_socket not visible in this container" \
            "Bind-mount it: -v /tmp/argus_socket:/tmp/argus_socket  (see setup_container.sh)"
    else
        fail "/tmp/argus_socket missing" "sudo systemctl restart nvargus-daemon"
    fi
fi
if find /usr/lib -maxdepth 3 -name 'libnvargus_socketclient.so*' 2>/dev/null | grep -q .; then
    ok "libnvargus_socketclient.so present"
else
    fail "libnvargus_socketclient.so not found" "Install the L4T Argus runtime (nvidia-l4t-camera)."
fi
if ARGUS_INC="$(find_argus_include)" && [[ -n "$ARGUS_INC" ]]; then
    ok "Argus headers: $ARGUS_INC"
else
    warn "Argus headers not found — needed only to build the camera_viz argus source"
    hint "Host: sudo apt-get install nvidia-l4t-jetson-multimedia-api"
fi

# --- Summary ----------------------------------------------------------------
printf '\n'
if [[ "$FAILED" -eq 0 ]]; then
    printf '%s%s All checks passed.%s\n' "$C_GREEN" "$C_BOLD" "$C_RESET"
else
    printf '%s%s Some checks failed — see the actions above.%s\n' "$C_RED" "$C_BOLD" "$C_RESET"
fi
exit "$FAILED"
