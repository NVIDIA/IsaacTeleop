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
            git \
            libssl-dev \
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
    if command -v wget &> /dev/null; then
        wget "$MANUS_SDK_URL" -O "$MANUS_SDK_ZIP"
    elif command -v curl &> /dev/null; then
        curl -L "$MANUS_SDK_URL" -o "$MANUS_SDK_ZIP"
    else
        echo "Error: Neither wget nor curl found. Please install one of them."
        exit 1
    fi
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

# Create build directory if it doesn't exist
if [ ! -d "build" ]; then
    mkdir -p build
fi

# Configure with CMake (only if needed)
if [ ! -f "build/CMakeCache.txt" ]; then
    echo "Configuring CMake..."
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
else
    echo "CMake already configured, skipping configuration..."
fi

# Build only the manus plugin (and its dependencies)
echo "Building..."
cmake --build build --target manus_hand_plugin -j$(nproc)

# Install only the manus component
echo "Installing..."
cmake --install build --component manus

echo ""
echo "=== Installation Complete ==="
echo "MANUS SDK v${MANUS_SDK_VERSION} installed to: $SCRIPT_DIR/ManusSDK"
echo "Plugin built and installed successfully"
echo "Plugin executable: $TELEOP_ROOT/install/plugins/manus/manus_hand_plugin"
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
