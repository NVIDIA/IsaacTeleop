#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Install the Manus udev rules on the HOST machine.
#
# udev rules are processed by systemd-udevd, which does not run inside Docker
# containers. They must therefore be installed on the host so that device nodes
# (/dev/hidraw*, /dev/bus/usb/.../...) come up with the permissions the Manus
# SDK needs. Once installed on the host, any container that bind-mounts
# /dev/bus/usb (or /dev) inherits the correct permissions.
#
# Run this once on the host, then unplug + replug the Manus dongle.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULES_SRC="$SCRIPT_DIR/70-manus-hid.rules"
RULES_DST="/etc/udev/rules.d/70-manus-hid.rules"
MANUS_USB_ID="3325:0049"
MANUS_VENDOR_ID="${MANUS_USB_ID%%:*}"

die() {
    echo "Error: $1" >&2
    if [[ "${2:-}" != "" ]]; then
        echo "Action: $2" >&2
    fi
    exit 1
}

warn() {
    echo "Warning: $1"
    if [[ "${2:-}" != "" ]]; then
        echo "Action:  $2"
    fi
    verification_ok=0
}

require_command() {
    local command_name="$1"
    local install_hint="$2"

    if ! command -v "$command_name" >/dev/null 2>&1; then
        die "required command '$command_name' was not found." "$install_hint"
    fi
}

if [[ ! -f "$RULES_SRC" ]]; then
    die "rules file not found at $RULES_SRC" "Run this script from a complete IsaacTeleop checkout."
fi

# Refuse to run inside a container — the udevadm reload would silently no-op
# and the user would think it worked.
if [[ -f /.dockerenv ]] || grep -qE '(docker|containerd|kubepods)' /proc/1/cgroup 2>/dev/null; then
    die "this script must be run on the HOST, not inside a container." \
        "Open a host terminal, cd to this IsaacTeleop checkout, and run: ./src/plugins/manus/install_udev_rules.sh"
fi

require_command udevadm "Install udev/systemd tools first, for example: sudo apt-get update && sudo apt-get install -y udev"
require_command stat "Install GNU coreutils first, for example: sudo apt-get update && sudo apt-get install -y coreutils"

# Pre-authenticate sudo if it would prompt for a password. Skipping `sudo -v`
# entirely on NOPASSWD setups — `sudo -v` always validates the password, even
# when the rules grant passwordless sudo, which would break unattended runs.
if ! sudo -n true 2>/dev/null; then
    echo "This script needs sudo to write to /etc/udev/rules.d/."
    sudo -v || die "sudo authentication failed." "Re-run from a user with sudo privileges."
fi

echo "Installing Manus udev rules to $RULES_DST..."
sudo install -m 0644 "$RULES_SRC" "$RULES_DST"

echo "Verifying installed rules file..."
if ! sudo test -f "$RULES_DST"; then
    die "rules file was not created at $RULES_DST" "Check sudo permissions and re-run this script."
fi
if ! sudo cmp -s "$RULES_SRC" "$RULES_DST"; then
    die "installed rules differ from $RULES_SRC" "Re-run this script, then inspect $RULES_DST if the mismatch remains."
fi

echo "Reloading udev rules..."
sudo udevadm control --reload-rules \
    || die "failed to reload udev rules." "Check that systemd-udevd is running, then run: sudo udevadm control --reload-rules"
sudo udevadm trigger --subsystem-match=usb --action=change \
    || die "failed to retrigger USB devices." "Try unplugging and replugging the Manus dongle, then re-run this script."
sudo udevadm trigger --subsystem-match=hidraw --action=change \
    || die "failed to retrigger hidraw devices." "Try unplugging and replugging the Manus dongle, then re-run this script."
sudo udevadm settle \
    || die "udev did not settle cleanly." "Wait a few seconds, unplug and replug the Manus dongle, then re-run this script."

verification_ok=1

echo "Verifying Manus USB device permissions..."
if ! command -v lsusb >/dev/null 2>&1; then
    warn "cannot check whether the Manus dongle is connected because 'lsusb' is not installed." \
        "Install it with: sudo apt-get update && sudo apt-get install -y usbutils"
else
    MANUS_USB_NODES="$(
        lsusb -d "$MANUS_USB_ID" 2>/dev/null \
            | awk '{ sub(/:$/, "", $4); printf "/dev/bus/usb/%s/%s\n", $2, $4 }' \
            || true
    )"

    if [[ -z "$MANUS_USB_NODES" ]]; then
        warn "Manus dongle was not detected on this host with 'lsusb -d $MANUS_USB_ID'." \
            "Plug the dongle into the host, unplug/replug it if already connected, then re-run this script."
    else
        while IFS= read -r manus_usb_node; do
            [[ -n "$manus_usb_node" ]] || continue

            if [[ ! -e "$manus_usb_node" ]]; then
                warn "lsusb found the Manus dongle, but $manus_usb_node does not exist." \
                    "Unplug and replug the dongle, then check again with: lsusb -d $MANUS_USB_ID"
                continue
            fi

            mode="$(stat -c '%a' "$manus_usb_node" 2>/dev/null || true)"
            if [[ "$mode" = "666" ]]; then
                echo "  OK: $manus_usb_node has mode 0666."
            else
                warn "$manus_usb_node has mode ${mode:-unknown}; expected 0666." \
                    "Unplug and replug the dongle. If it stays wrong, run: sudo udevadm trigger --subsystem-match=usb --action=change && sudo udevadm settle"
            fi
        done <<< "$MANUS_USB_NODES"
    fi
fi

echo "Verifying optional Manus hidraw device permissions..."
hidraw_seen=0
for hidraw_node in /dev/hidraw*; do
    [[ -e "$hidraw_node" ]] || continue

    if udevadm info -q property -n "$hidraw_node" 2>/dev/null | grep -q "^ID_VENDOR_ID=$MANUS_VENDOR_ID$"; then
        hidraw_seen=1
        mode="$(stat -c '%a' "$hidraw_node" 2>/dev/null || true)"
        if [[ "$mode" = "666" ]]; then
            echo "  OK: $hidraw_node has mode 0666."
        else
            warn "$hidraw_node has mode ${mode:-unknown}; expected 0666." \
                "Unplug and replug the dongle. If it stays wrong, run: sudo udevadm trigger --subsystem-match=hidraw --action=change && sudo udevadm settle"
        fi
    fi
done

if [[ "$hidraw_seen" -eq 0 ]]; then
    echo "  No Manus hidraw nodes found. This is okay for dongles that only expose /dev/bus/usb."
fi

echo ""
if [[ "$verification_ok" -eq 1 ]]; then
    echo "=== Done ==="
    echo "Manus udev rules are installed, reloaded, and detected device permissions look correct."
    echo "If a container was already running, restart it so it sees the updated host device permissions."
else
    echo "=== Installed, with follow-up actions ==="
    echo "The udev rules were installed and reloaded, but verification found the issue(s) above."
    echo "After completing the suggested action(s), re-run this script to verify the host setup."
fi
