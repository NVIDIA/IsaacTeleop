#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -e  # Exit on error
set -u  # Exit on undefined variable

echo "=== Dependency Setup for Debian/Ubuntu ==="

# Install required packages including GCC-11 for compatibility
echo "[1/7] Installing build dependencies and GCC-11..."

# Check if GCC-11 is available, if not add appropriate repo
if ! apt-cache show gcc-11 &>/dev/null; then
    echo "GCC-11 not found in current repos."
    # Detect if running Ubuntu or Debian
    if grep -qi "ubuntu" /etc/os-release; then
        echo "Adding Ubuntu Toolchain PPA for GCC-11..."
        apt-get install -y software-properties-common
        add-apt-repository -y ppa:ubuntu-toolchain-r/test
    else
        echo "Adding Debian 12 (Bookworm) repository for GCC-11..."
        apt-get install -y debian-archive-keyring
        echo "deb http://deb.debian.org/debian bookworm main" | tee /etc/apt/sources.list.d/bookworm-gcc.list
    fi
fi

apt-get update
apt-get install -y \
    build-essential \
    gcc-11 \
    g++-11 \
    cmake \
    git \
    libtool \
    libssl-dev \
    zlib1g-dev

echo "Using GCC-11 to compile gRPC v1.28.1 (GCC-12+ is incompatible)"

echo "[2/7] Cloning gRPC repository..."
mkdir -p /var/local/git
if [ ! -d "/var/local/git/grpc" ]; then
    git clone --recurse-submodules -b v1.28.1 --depth 1 https://github.com/grpc/grpc /var/local/git/grpc
else
    echo "gRPC repository already exists, skipping clone"
fi

# Check if running on x86_64
if [ "$(uname -m)" == "x86_64" ]; then
    echo "[3/7] Building protobuf for x86_64..." && \
    cd /var/local/git/grpc/third_party/protobuf && \
    ./autogen.sh && ./configure --enable-shared && \
    make -j$(nproc) && make -j$(nproc) check && make install && ldconfig
else
    echo "[3/7] Not running on x86_64, Building protobuf for x86_64 SKIPPED."
fi 

# Patch abseil-cpp for GCC 11+ compatibility
echo "[4/7] Patching abseil-cpp for GCC compatibility..."
if ! grep -q '#include <limits>' /var/local/git/grpc/third_party/abseil-cpp/absl/synchronization/internal/graphcycles.cc; then
    sed -i '1i#include <limits>' /var/local/git/grpc/third_party/abseil-cpp/absl/synchronization/internal/graphcycles.cc
fi
if grep -q 'std::max(SIGSTKSZ, 65536)' /var/local/git/grpc/third_party/abseil-cpp/absl/debugging/failure_signal_handler.cc 2>/dev/null; then
    sed -i 's/std::max(SIGSTKSZ, 65536)/std::max<size_t>(SIGSTKSZ, 65536)/' /var/local/git/grpc/third_party/abseil-cpp/absl/debugging/failure_signal_handler.cc
fi

# Add missing cstdint include for uint64_t
if ! grep -q '#include <cstdint>' /var/local/git/grpc/third_party/abseil-cpp/absl/strings/internal/str_format/extension.h; then
    sed -i '/#include "absl\/strings\/string_view.h"/a #include <cstdint>' /var/local/git/grpc/third_party/abseil-cpp/absl/strings/internal/str_format/extension.h
    echo "Added <cstdint> include to extension.h"
fi

# Build protobuf natively with GCC-11
if [ "$(uname -m)" == "aarch64" ]; then
    echo "[5/7] Building protobuf for ARM64 with GCC-11..."
    mkdir -p /var/local/git/grpc/third_party/protobuf/build
    cd /var/local/git/grpc/third_party/protobuf/build
    CC=gcc-11 CXX=g++-11 cmake ../cmake \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -Dprotobuf_BUILD_TESTS=OFF \
        -Dprotobuf_WITH_ZLIB=ON \
        -Dprotobuf_BUILD_SHARED_LIBS=ON
    make -j$(nproc)
    make install
    ldconfig
else
    echo "[5/7] Not running on aarch64, Building protobuf for ARM64 SKIPPED."
fi

echo "Protobuf installed: $(protoc --version)"

# Build gRPC natively with GCC-11
echo "[6/7] Building gRPC v1.28.1 with GCC-11..."
mkdir -p /var/local/git/grpc/build
cd /var/local/git/grpc/build
CC=gcc-11 CXX=g++-11 cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DgRPC_INSTALL=ON \
    -DgRPC_BUILD_TESTS=OFF \
    -DBUILD_SHARED_LIBS=ON \
    -DgRPC_PROTOBUF_PROVIDER=package \
    -DgRPC_ZLIB_PROVIDER=package \
    -DgRPC_CARES_PROVIDER=module \
    -DgRPC_SSL_PROVIDER=package \
    -DgRPC_BUILD_CSHARP_EXT=OFF
make -j$(nproc)
make install
ldconfig

echo "[7/7] Installing additional dependencies..."
apt-get install -y \
    libc-ares-dev \
    libzmq3-dev \
    libncurses-dev \
    libudev-dev \
    libusb-1.0-0-dev
    
# Configure library path persistently
echo "[Setup] Configuring library path..."
if [ ! -f "/etc/ld.so.conf.d/local-libs.conf" ]; then
    echo "/usr/local/lib" | tee /etc/ld.so.conf.d/local-libs.conf > /dev/null
    ldconfig
    echo "Added /usr/local/lib to ld.so.conf"
fi

# Add read/write permissions for manus devices
if [ ! -f "/etc/udev/rules.d/70-manus-hid.rules" ]; then
    mkdir -p /etc/udev/rules.d/
    touch /etc/udev/rules.d/70-manus-hid.rules
    echo "[Setup] Adding read/write permissions for manus devices..."
    echo "# HIDAPI/libusb" >> /etc/udev/rules.d/70-manus-hid.rules
    echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"3325\", MODE:=\"0666\"" >> /etc/udev/rules.d/70-manus-hid.rules
    echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"1915\", ATTRS{idProduct}==\"83fd\", MODE:=\"0666\"" >> /etc/udev/rules.d/70-manus-hid.rules
    echo "# HIDAPI/hidraw" >> /etc/udev/rules.d/70-manus-hid.rules
    echo "KERNEL==\"hidraw*\", ATTRS{idVendor}==\"3325\", MODE:=\"0666\"" >> /etc/udev/rules.d/70-manus-hid.rules
fi

echo ""
echo "=== Setup Complete ==="
echo "gRPC v1.28.1 and protobuf compiled successfully with GCC-11"
echo "Libraries installed to: /usr/local/lib"
echo "Headers installed to: /usr/local/include"
echo ""
echo "To use these libraries in your current shell session:"
echo "  export LD_LIBRARY_PATH=/usr/local/lib"
echo ""
echo "Library path has been configured system-wide via ldconfig."
echo ""
echo "Udev rules have been configured to allow read/write access to manus devices."
echo "You may need to reload udev rules for the changes to take effect by running the following commands:"
echo "  sudo udevadm control --reload-rules"
echo "  sudo udevadm trigger"
echo ""
echo "Installed versions:"
echo "  - Protobuf: $(protoc --version)"
echo "  - Compiler: $(gcc-11 --version | head -n1)"
echo ""
echo "You can now build your SDK project with gRPC v1.28.1."