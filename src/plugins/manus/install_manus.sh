#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# MANUS SDK installation script.
#
# By default, prints concise high-level progress and hides the chatter from
# apt-get / curl / cmake. Use --verbose to see every command's full output.

set -euo pipefail

# --- Arg parsing ---------------------------------------------------------
VERBOSE=0
BUILD_DIR=""
FORCE_CONTAINER=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--verbose) VERBOSE=1; shift ;;
        --container) FORCE_CONTAINER=1; shift ;;
        --build-dir)
            BUILD_DIR="${2:?--build-dir requires a non-empty path}"
            shift 2
            ;;
        -h|--help)
            cat <<EOF
Usage: $(basename "$0") [--verbose] [--container] [--build-dir <path>]

Installs the MANUS SDK and builds the Manus Teleop plugin.

Options:
  --build-dir <path>  CMake build directory (default: <isaacteleop-root>/build).
  --container         Skip host udev setup when auto-detection is unavailable.
  -v, --verbose       Show full output from apt-get, curl, cmake, etc.
  -h, --help          Show this help.
EOF
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Run with --help for usage." >&2
            exit 1
            ;;
    esac
done

# --- Configuration -------------------------------------------------------
MANUS_SDK_VERSION="3.2.0"
# Since 3.2 the SDK ships per-platform; the Linux package is a tarball.
MANUS_SDK_ARCHIVE="MANUS_Core_${MANUS_SDK_VERSION}_SDK_Linux.tar.gz"
MANUS_SDK_URL="https://static.manus-meta.com/resources/manus_core_3/sdk/${MANUS_SDK_ARCHIVE}"
MANUS_SDK_SHA256_ACCEPTED=(
    "02821f0b6d1f45645ffb63fdc5b5c312211b3a9cfbcd9b701584fd2feed0a432"
)
# Directory inside the tarball that holds include/ and lib/<arch>/.
MANUS_SDK_TAR_PREFIX="C++/SDKClient/ManusSDK"

HOST_ARCH="$(uname -m)"
case "$HOST_ARCH" in
    x86_64) MANUS_SDK_ARCH="amd64" ;;
    aarch64|arm64) MANUS_SDK_ARCH="aarch64" ;;
    *)
        echo "Unsupported architecture: $HOST_ARCH (MANUS SDK supports x86_64 and aarch64)" >&2
        exit 1
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TELEOP_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$TELEOP_ROOT/build}"
if [[ "$BUILD_DIR" != /* ]]; then
    BUILD_DIR="$PWD/$BUILD_DIR"
fi

# --- Output helpers ------------------------------------------------------
LOG_FILE=$(mktemp -t manus_install.XXXXXX.log)
TMP_EXTRACT_DIR=""
TMP_ARCHIVE=""
cleanup() {
    rm -f "$LOG_FILE"
    if [[ -n "$TMP_ARCHIVE" ]]; then rm -f "$TMP_ARCHIVE"; fi
    if [[ -n "$TMP_EXTRACT_DIR" ]]; then rm -rf "$TMP_EXTRACT_DIR"; fi
}
trap cleanup EXIT

# ANSI colors, but only when stdout is a TTY so logs/pipes stay clean.
if [[ -t 1 ]]; then
    C_BOLD=$'\033[1m'
    C_RED=$'\033[31m'
    C_YELLOW=$'\033[33m'
    C_RESET=$'\033[0m'
else
    C_BOLD='' C_RED='' C_YELLOW='' C_RESET=''
fi

step() { printf '\n==> %s\n' "$*"; }
done_ok() { printf '    done.\n'; }
die() {
    printf '    FAILED: %s\n' "$*" >&2
    if [[ "$VERBOSE" -eq 0 ]] && [[ -s "$LOG_FILE" ]]; then
        printf -- '\n--- last 50 lines of command output ---\n' >&2
        tail -n 50 "$LOG_FILE" >&2
        printf -- '--- (re-run with --verbose for full output) ---\n' >&2
    fi
    exit 1
}

# Run a command; in quiet mode, redirect stdout+stderr to the log file.
run() {
    if [[ "$VERBOSE" -eq 1 ]]; then
        "$@"
    else
        "$@" >>"$LOG_FILE" 2>&1
    fi
}

in_container() {
    [[ -f /.dockerenv ]] || grep -qE '(docker|containerd|kubepods)' /proc/1/cgroup 2>/dev/null
}

# --- Banner --------------------------------------------------------------
echo "=== MANUS SDK Installation ==="
echo "Architecture: $HOST_ARCH (SDK library: $MANUS_SDK_ARCH)"
if [[ "$FORCE_CONTAINER" -eq 1 ]] || in_container; then
    CONTAINER=1
    echo "Environment:  container (udev step will be skipped)"
else
    CONTAINER=0
    echo "Environment:  host"
fi
if [[ "$VERBOSE" -eq 0 ]]; then
    echo "(re-run with --verbose to see full command output)"
fi

# Pre-authenticate sudo once, up front, so quiet-mode redirection doesn't
# swallow the password prompt later. Skip if sudo is already passwordless
# (e.g. NOPASSWD in /etc/sudoers.d/) — `sudo -v` would still prompt in that
# case, which breaks unattended container setups.
if ! sudo -n true 2>/dev/null; then
    echo ""
    echo "This script needs sudo for apt-get and udev install."
    sudo -v || die "sudo authentication failed"
fi

# --- 1. System dependencies ---------------------------------------------
# gRPC and protobuf are statically linked into libManusSDK.so since MANUS Core
# 3.2, so their build dependencies are no longer installed here.
APT_PACKAGES=(
    build-essential
    cmake
    curl
    git
    tar
    libzmq3-dev
    libncurses-dev
    libudev-dev
    libusb-1.0-0-dev
    libvulkan-dev
    libx11-dev
)

step "[1/4] Checking system dependencies"
missing_pkgs=()
for pkg in "${APT_PACKAGES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed"; then
        missing_pkgs+=("$pkg")
    fi
done
if [[ "${#missing_pkgs[@]}" -eq 0 ]]; then
    echo "    all ${#APT_PACKAGES[@]} packages already installed; skipping apt."
else
    echo "    ${#missing_pkgs[@]} missing: ${missing_pkgs[*]}"
    run sudo apt-get update -qq || die "apt-get update failed"
    run sudo apt-get install -y -qq "${missing_pkgs[@]}" || die "apt-get install failed"
fi
done_ok

# --- 2. udev rules (host only) ------------------------------------------
if [[ "$CONTAINER" -eq 0 ]]; then
    step "[2/4] Installing host udev rules for Manus devices"
    # install_udev_rules.sh is the single source of truth for udev setup.
    run bash "$SCRIPT_DIR/install_udev_rules.sh" || die "udev rules install failed"
    done_ok
else
    step "[2/4] udev rules: skipped (running inside container)"
    echo "    See post-install instructions at the end."
fi

# --- 3. SDK download and extract ----------------------------------------
step "[3/4] Downloading and extracting MANUS SDK v${MANUS_SDK_VERSION}"
cd "$SCRIPT_DIR"

if [[ -f "$MANUS_SDK_ARCHIVE" ]]; then
    echo "    SDK archive already exists. Skipping download."
else
    # Download to a .tmp path and rename on success so a partial/aborted
    # download never leaves a file that looks complete on the next run.
    TMP_ARCHIVE="$SCRIPT_DIR/${MANUS_SDK_ARCHIVE}.tmp"
    if command -v curl &> /dev/null; then
        if [[ "$VERBOSE" -eq 1 ]]; then
            # -f: fail on HTTP errors (4xx/5xx), -L: follow redirects
            curl -fL "$MANUS_SDK_URL" -o "$TMP_ARCHIVE" || die "SDK download failed"
        else
            # -fsSL: silent but show errors, follow redirects
            curl -fsSL "$MANUS_SDK_URL" -o "$TMP_ARCHIVE" || die "SDK download failed"
        fi
    elif command -v wget &> /dev/null; then
        run wget -q "$MANUS_SDK_URL" -O "$TMP_ARCHIVE" || die "SDK download failed"
    else
        die "Neither curl nor wget found"
    fi
    mv "$TMP_ARCHIVE" "$MANUS_SDK_ARCHIVE"
    TMP_ARCHIVE=""
fi

ACTUAL_SHA256=$(sha256sum "$MANUS_SDK_ARCHIVE" | awk '{print $1}')
sha_match=0
for expected in "${MANUS_SDK_SHA256_ACCEPTED[@]}"; do
    if [[ "$ACTUAL_SHA256" = "$expected" ]]; then
        sha_match=1
        break
    fi
done
if [[ "$sha_match" -ne 1 ]]; then
    rm -f "$MANUS_SDK_ARCHIVE"
    die "SHA-256 mismatch (got $ACTUAL_SHA256; accepted: ${MANUS_SDK_SHA256_ACCEPTED[*]})"
fi

# The tarball also carries the Python/ROS2/dashboard packages; only unpack the
# C++ headers and the shared library for this architecture.
TMP_EXTRACT_DIR=$(mktemp -d -t manus_sdk.XXXXXX)
run tar -xzf "$MANUS_SDK_ARCHIVE" -C "$TMP_EXTRACT_DIR" \
    "$MANUS_SDK_TAR_PREFIX/include" "$MANUS_SDK_TAR_PREFIX/lib/$MANUS_SDK_ARCH" \
    || die "extraction failed"

SDK_SRC="$TMP_EXTRACT_DIR/$MANUS_SDK_TAR_PREFIX"
SDK_LIB_SRC="$SDK_SRC/lib/$MANUS_SDK_ARCH/libManusSDK-${MANUS_SDK_ARCH}.so"
[[ -f "$SDK_SRC/include/ManusSDK.h" ]] || die "ManusSDK.h not found in $MANUS_SDK_ARCHIVE"
[[ -f "$SDK_LIB_SRC" ]] || die "No $MANUS_SDK_ARCH library found in $MANUS_SDK_ARCHIVE"

rm -rf "$SCRIPT_DIR/ManusSDK"
mkdir -p "$SCRIPT_DIR/ManusSDK/lib"
cp -r "$SDK_SRC/include" "$SCRIPT_DIR/ManusSDK/"
# Drop the arch suffix: the build expects a single lib/libManusSDK.so, which
# since 3.2 serves both integrated and remote modes.
cp "$SDK_LIB_SRC" "$SCRIPT_DIR/ManusSDK/lib/libManusSDK.so"
rm -rf "$TMP_EXTRACT_DIR"
TMP_EXTRACT_DIR=""
# Keep the archive for re-runs; SHA-256 verification above guards against corruption.
done_ok

# --- 4. Build the plugin ------------------------------------------------
step "[4/4] Building Manus plugin"
cd "$TELEOP_ROOT"
run cmake -S . -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release -DBUILD_PLUGINS=ON \
    -DBUILD_VIZ=OFF -DENABLE_CLANG_FORMAT_CHECK=OFF \
    -DMANUS_SDK_ROOT="$SCRIPT_DIR/ManusSDK" \
    || die "cmake configure failed"
run cmake --build "$BUILD_DIR" \
    --target manus_hand_plugin manus_hand_tracker_printer -j"$(nproc)" \
    || die "build failed"
run cmake --install "$BUILD_DIR" --component manus || die "install failed"
done_ok

# --- Done ---------------------------------------------------------------
INSTALL_PREFIX="$(awk '/^CMAKE_INSTALL_PREFIX:PATH=/{sub(/^[^=]*=/, ""); print; exit}' "$BUILD_DIR/CMakeCache.txt")"
cat <<EOF

=== Installation Complete ===
  SDK:                $SCRIPT_DIR/ManusSDK
  Plugin executable:  $INSTALL_PREFIX/plugins/manus/manus_hand_plugin
  Printer diagnostic: $BUILD_DIR/bin/manus_hand_tracker_printer
EOF

if [[ "$CONTAINER" -eq 1 ]]; then
    cat <<EOF

${C_YELLOW}==================================================================${C_RESET}
  ${C_BOLD}${C_RED}ACTION REQUIRED:${C_RESET} ${C_BOLD}HOST-SIDE SETUP${C_RESET}

  The Manus dongle is NOT yet accessible from this container.
  udev rules must be installed on the HOST machine.

  On the host (not in this container), cd into your IsaacTeleop
  checkout and run:

      ${C_BOLD}./src/plugins/manus/install_udev_rules.sh${C_RESET}

  Then unplug and replug the Manus dongle, and restart this
  container so it picks up the device.
${C_YELLOW}==================================================================${C_RESET}
EOF
else
    echo ""
    echo "Reminder: unplug and replug the Manus dongle so the new udev rules take effect."
fi
