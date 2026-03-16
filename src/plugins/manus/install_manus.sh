#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e  # Exit on error
set -u  # Exit on undefined variable

echo "=== MANUS SDK Installation Script ==="
echo ""

# Define SDK download URL and version
MANUS_SDK_VERSION="3.1.1"
MANUS_SDK_URL="https://static.manus-meta.com/resources/manus_core_3/sdk/MANUS_Core_${MANUS_SDK_VERSION}_SDK.zip"
MANUS_SDK_ZIP="MANUS_Core_${MANUS_SDK_VERSION}_SDK.zip"
MANUS_SDK_SHA256="c5ccd3c42a501107ec79f70d8450a486fbc3925c5c1e18e606114d09f2d9d24a"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect architecture
ARCH=$(uname -m)
echo "Detected architecture: $ARCH"
echo ""

# Query user for dependency installation type
echo "MANUS Core dependencies installation options:"
echo "  1) Install MANUS Core Integrated dependencies only (faster)"
echo "  2) Install both MANUS Core Integrated and Remote dependencies (includes gRPC, takes longer)"
echo ""
read -p "Enter your choice (1 or 2): " INSTALL_CHOICE

case "$INSTALL_CHOICE" in
    1)
        echo "Installing MANUS Core Integrated dependencies only..."
        INSTALL_REMOTE=false
        ;;
    2)
        echo "Installing MANUS Core Integrated and Remote dependencies..."
        INSTALL_REMOTE=true
        ;;
    *)
        echo "Invalid choice. Defaulting to option 1 (Integrated only)."
        INSTALL_REMOTE=false
        ;;
esac
echo ""

# Run the dependency installation script
if [ -f "$SCRIPT_DIR/install-dependencies.sh" ]; then
    echo "[1/4] Running dependency installation script..."
    if [ "$INSTALL_REMOTE" = true ]; then
        sudo bash "$SCRIPT_DIR/install-dependencies.sh"
    else
        echo "Skipping Remote dependencies (gRPC installation)..."
        echo "Installing minimal dependencies only..."
        sudo apt-get update
        sudo apt-get install -y \
            build-essential \
            cmake \
            curl \
            git \
            libssl-dev \
            unzip \
            zlib1g-dev \
            libc-ares-dev \
            libzmq3-dev \
            libncurses-dev \
            libudev-dev \
            libusb-1.0-0-dev
        
        # Add read/write permissions for manus devices
        if [ ! -f "/etc/udev/rules.d/70-manus-hid.rules" ]; then
            sudo mkdir -p /etc/udev/rules.d/
            sudo touch /etc/udev/rules.d/70-manus-hid.rules
            echo "Adding read/write permissions for manus devices..."
            echo "# HIDAPI/libusb" | sudo tee -a /etc/udev/rules.d/70-manus-hid.rules > /dev/null
            echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"3325\", MODE:=\"0666\"" | sudo tee -a /etc/udev/rules.d/70-manus-hid.rules > /dev/null
            echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"1915\", ATTRS{idProduct}==\"83fd\", MODE:=\"0666\"" | sudo tee -a /etc/udev/rules.d/70-manus-hid.rules > /dev/null
            echo "# HIDAPI/hidraw" | sudo tee -a /etc/udev/rules.d/70-manus-hid.rules > /dev/null
            echo "KERNEL==\"hidraw*\", ATTRS{idVendor}==\"3325\", MODE:=\"0666\"" | sudo tee -a /etc/udev/rules.d/70-manus-hid.rules > /dev/null
            sudo udevadm control --reload-rules
        fi
    fi
    echo ""
else
    echo "Warning: install-dependencies.sh not found. Skipping dependency installation."
    echo ""
fi

# Download MANUS SDK
echo "[2/4] Downloading MANUS SDK v${MANUS_SDK_VERSION}..."
cd "$SCRIPT_DIR"

if [ -f "$MANUS_SDK_ZIP" ]; then
    echo "SDK archive already exists. Skipping download."
else
    if command -v curl &> /dev/null; then
        # -f: fail on HTTP errors (4xx/5xx), -L: follow redirects
        curl -fL "$MANUS_SDK_URL" -o "$MANUS_SDK_ZIP"
    elif command -v wget &> /dev/null; then
        # --server-response prints HTTP status; wget already exits non-zero on errors
        wget --server-response "$MANUS_SDK_URL" -O "$MANUS_SDK_ZIP"
    else
        echo "Error: Neither curl nor wget found. Please install curl (apt-get install curl)."
        exit 1
    fi
fi

# Verify archive integrity before extracting
if [ -n "${MANUS_SDK_SHA256:-}" ]; then
    echo "Verifying SDK archive checksum..."
    ACTUAL_SHA256=$(sha256sum "$MANUS_SDK_ZIP" | awk '{print $1}')
    if [ "$ACTUAL_SHA256" != "$MANUS_SDK_SHA256" ]; then
        echo "Error: SHA-256 checksum mismatch for $MANUS_SDK_ZIP"
        echo "  Expected: $MANUS_SDK_SHA256"
        echo "  Actual:   $ACTUAL_SHA256"
        echo "The archive may be corrupted or tampered with. Aborting."
        rm -f "$MANUS_SDK_ZIP"
        exit 1
    fi
    echo "Checksum verified."
else
    echo "Warning: MANUS_SDK_SHA256 is not set. Skipping checksum verification."
    echo "         Set MANUS_SDK_SHA256 in install_manus.sh to enable integrity checking."
fi
echo ""

# Extract SDK and copy ManusSDK folder
echo "[3/4] Extracting MANUS SDK..."

# Remove existing ManusSDK if present
if [ -d "$SCRIPT_DIR/ManusSDK" ]; then
    echo "Removing existing ManusSDK directory..."
    rm -rf "$SCRIPT_DIR/ManusSDK"
fi

# Extract the archive
if command -v unzip &> /dev/null; then
    unzip -q "$MANUS_SDK_ZIP"
else
    echo "Error: unzip command not found. Please install unzip."
    exit 1
fi

SDK_CLIENT_DIR="SDKClient_Linux"

# Find and copy ManusSDK folder
EXTRACTED_DIR=$(find . -maxdepth 1 -type d -name "ManusSDK_v*" | head -n 1)
if [ -z "$EXTRACTED_DIR" ]; then
    echo "Error: Could not find extracted SDK directory."
    exit 1
fi

if [ -d "$EXTRACTED_DIR/$SDK_CLIENT_DIR/ManusSDK" ]; then
    echo "Copying ManusSDK folder from $SDK_CLIENT_DIR..."
    cp -r "$EXTRACTED_DIR/$SDK_CLIENT_DIR/ManusSDK" "$SCRIPT_DIR/"
    echo "ManusSDK copied successfully to $SCRIPT_DIR/ManusSDK"
    
    if [ "$INSTALL_REMOTE" = true ]; then
        echo "Note: Both libManusSDK.so and libManusSDK_Integrated.so available."
        echo "CMake will use libManusSDK_Integrated.so by default."
    else
        echo "Note: Using libManusSDK_Integrated.so (CMake auto-selects)."
    fi
else
    echo "Error: ManusSDK folder not found in $EXTRACTED_DIR/$SDK_CLIENT_DIR"
    exit 1
fi

# Clean up extracted directory and zip file
echo "Cleaning up temporary files..."
rm -rf "$EXTRACTED_DIR"
rm -f "$MANUS_SDK_ZIP"
echo ""

# Build the plugin
echo "[4/4] Building Manus plugin from TeleopCore root..."

# Find TeleopCore root (3 levels up from src/plugins/manus)
TELEOP_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$TELEOP_ROOT"

echo "TeleopCore root: $TELEOP_ROOT"

echo "Configuring CMake..."
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release

# Build the plugin and the diagnostic printer tool
echo "Building..."
cmake --build build --target manus_hand_plugin manus_hand_tracker_printer -j$(nproc)

# Install only the manus component
echo "Installing..."
cmake --install build --component manus

echo ""
echo "=== Installation Complete ==="
echo "MANUS SDK v${MANUS_SDK_VERSION} installed to: $SCRIPT_DIR/ManusSDK"
echo "Plugin built and installed successfully"
echo "Plugin executable:  $TELEOP_ROOT/install/plugins/manus/manus_hand_plugin"
echo "Printer diagnostic: $TELEOP_ROOT/build/bin/manus_hand_tracker_printer"
echo ""
if [ "$INSTALL_REMOTE" = false ]; then
    echo "Note: Only MANUS Core Integrated dependencies were installed."
    echo "If you need Remote functionality (gRPC), re-run and select option 2."
fi
echo ""
echo "To reload udev rules (if not already done), run:"
echo "  sudo udevadm control --reload-rules"
echo "  sudo udevadm trigger"
echo ""
