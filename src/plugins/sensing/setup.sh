#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Entry point for SENSING SG10A camera setup. Detects whether it is running on
# the Jetson host or inside a container and delegates to the right half; every
# argument is forwarded unchanged.
#
# Setup is genuinely two-sided: kernel modules, device-tree overlays and the
# POC/PWM register writes only exist on the host, while the Argus client socket
# and build headers only matter inside the container. Run it in both places.
#
# Usage:
#   ./setup.sh [--host|--container] [options...]
#
#   --host       force the host path (see setup_host.sh --help)
#   --container  force the container path (see setup_container.sh --help)
#   --verify     run the read-only health report and exit
#
# With no flag the context is auto-detected.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
source "$SCRIPT_DIR/_common.sh"

usage() { sed -n '4,21p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; }

TARGET=auto
case "${1:-}" in
    --host)      TARGET=host; shift ;;
    --container) TARGET=container; shift ;;
    --verify)    shift; exec "$SCRIPT_DIR/verify.sh" "$@" ;;
    -h|--help)   usage; exit 0 ;;
esac

if [[ "$TARGET" == auto ]]; then
    if in_container; then TARGET=container; else TARGET=host; fi
    info "detected context: $TARGET  ${C_DIM}(override with --host / --container)${C_RESET}"
fi

exec "$SCRIPT_DIR/setup_${TARGET}.sh" "$@"
