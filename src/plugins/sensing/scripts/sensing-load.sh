#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Root-only, idempotent driver load for the SENSING rig. Shared by setup_host.sh
# (interactively, via sudo) and by sensing-camera.service (at boot, as root), so
# both paths bring the rig up identically.
#
# Do not add prompts or colour here — it runs under systemd with no tty.
#
# Usage:
#   sensing-load.sh --pkg DIR [--fps N] [--free-run] [--restart-argus]
#
#   --restart-argus  restart nvargus-daemon afterwards. Correct for an
#                    interactive run; wrong under the boot unit, which is
#                    already ordered Before=nvargus-daemon.service.

set -euo pipefail

PKG_DIR=""
FPS=30
FREE_RUN=0
RESTART_ARGUS=0
SHF3L_NODES=(4 5 6 7 8 9)

while (( $# )); do
    case "$1" in
        --pkg)            PKG_DIR="$2"; shift 2 ;;
        --fps)            FPS="$2"; shift 2 ;;
        --free-run)       FREE_RUN=1; shift ;;
        --restart-argus)  RESTART_ARGUS=1; shift ;;
        *) echo "sensing-load.sh: unknown argument: $1" >&2; exit 1 ;;
    esac
done

[[ "$(id -u)" -eq 0 ]] || { echo "sensing-load.sh: must run as root" >&2; exit 1; }
[[ -n "$PKG_DIR" && -f "$PKG_DIR/load_modules.sh" ]] \
    || { echo "sensing-load.sh: --pkg must point at the vendor package (got '$PKG_DIR')" >&2; exit 1; }

# load_modules.sh resolves ./ko/*.ko and ./gpio-pwm.sh relative to $PWD, and
# rmmods before insmod, so re-running it is the supported way to reload.
echo "sensing-load: loading drivers from $PKG_DIR at ${FPS} Hz"
cd "$PKG_DIR"
./load_modules.sh "$FPS"

if [[ "$FREE_RUN" -eq 1 ]]; then
    if ! command -v v4l2-ctl >/dev/null 2>&1; then
        echo "sensing-load: v4l2-ctl missing, cannot set free-run mode" >&2
        exit 1
    fi
    for dev in /dev/video*; do
        [[ -e "$dev" ]] || continue
        i="${dev#/dev/video}"
        ctrls="trig_mode=0"
        for s in "${SHF3L_NODES[@]}"; do [[ "$i" == "$s" ]] && ctrls="sensor_mode=2,trig_mode=0"; done
        # An unpopulated port rejects the write; that is expected, not fatal.
        if v4l2-ctl -d "$dev" -c "$ctrls" 2>/dev/null; then
            echo "sensing-load: $dev -> $ctrls"
        else
            echo "sensing-load: $dev skipped (no module on that port)"
        fi
    done
fi

if [[ "$RESTART_ARGUS" -eq 1 ]]; then
    # nvargus-daemon enumerates sensors once at startup; a daemon that started
    # before the drivers loaded reports an empty camera list until restarted.
    echo "sensing-load: restarting nvargus-daemon"
    systemctl restart nvargus-daemon
fi
