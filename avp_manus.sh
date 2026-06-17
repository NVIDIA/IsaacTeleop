#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# IsaacTeleop AVP + MANUS + G1-Wuji demo runbook
#
# Notes:
# 1. This file is a step-by-step command guide. Do not execute it end to end
#    with `bash avp_manus.sh`.
# 2. A working team Isaac Lab environment is assumed. Isaac Lab installation
#    steps are intentionally omitted here.
# 3. This demo defaults to `examples/g1_wuji_teleop/config/avp_manus.yml`.
#    It uses `retargeting.method=official_wuji`, so the
#    `third_party/wuji-retargeting` submodule must be initialized first.
# 4. The commands below assume Python 3.12. The Python major/minor version used
#    to build `isaacteleop` must match the Python version in your Isaac Lab
#    environment. If your Isaac Lab is not using 3.12, update the `3.12`
#    references below accordingly.
#
# -----------------------------------------------------------------------------
# 0. Enter the repository root
# -----------------------------------------------------------------------------

cd /path/to/IsaacTeleop

# -----------------------------------------------------------------------------
# 1. Install Ubuntu system dependencies
# -----------------------------------------------------------------------------

sudo apt-get update
sudo apt-get install -y \
    build-essential \
    cmake \
    clang-format-14 \
    ccache \
    patchelf \
    curl \
    git \
    unzip \
    usbutils \
    android-tools-adb \
    coturn \
    libx11-dev \
    libssl-dev \
    zlib1g-dev \
    libc-ares-dev \
    libzmq3-dev \
    libncurses-dev \
    libudev-dev \
    libusb-1.0-0-dev \
    libvulkan-dev \
    glslang-tools \
    libxrandr-dev \
    libxinerama-dev \
    libxcursor-dev \
    libxi-dev \
    libxext-dev \
    libxkbcommon-dev \
    libwayland-dev \
    wayland-protocols

# -----------------------------------------------------------------------------
# 2. Create and activate the `isaacteleop` conda environment
# -----------------------------------------------------------------------------

conda create -n isaacteleop python=3.12 -y
conda activate isaacteleop
# From PyPI
pip install 'isaacteleop[cloudxr,retargeters]~=1.0.0' --extra-index-url https://pypi.nvidia.com
# python -m pip install --upgrade pip
# python -m pip install uv pre-commit

# -----------------------------------------------------------------------------
# 3. Build IsaacTeleop from source and install the wheel into the `isaacteleop`
#    conda environment
# -----------------------------------------------------------------------------

cd /path/to/IsaacTeleop

cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DISAAC_TELEOP_PYTHON_VERSION=3.12 \
    -DBUILD_VIZ=OFF \
    -DBUILD_PLUGIN_OAK_CAMERA=OFF \
    -DENABLE_CLANG_FORMAT_CHECK=OFF

cmake --build build --parallel "$(nproc)"
cmake --install build

python -m pip install -r /path/to/IsaacTeleop/src/core/python/requirements-retargeters.txt
python -m pip install -r /path/to/IsaacTeleop/src/core/python/requirements-cloudxr.txt
python -m pip install --force-reinstall /path/to/IsaacTeleop/install/wheels/isaacteleop-*.whl

python -c "import isaacteleop, isaacteleop.cloudxr, isaacteleop.retargeters; print(isaacteleop.__file__)"

# -----------------------------------------------------------------------------
# 4. Pull the wuji official wuji-retargeting
# -----------------------------------------------------------------------------
cd /path/to/IsaacTeleop
git submodule update --init --recursive third_party/wuji-retargeting

# -----------------------------------------------------------------------------
# 5. Install MANUS host permissions and the SDK / plugin
# -----------------------------------------------------------------------------

cd /path/to/IsaacTeleop/src/plugins/manus

# 5.1 This step must run on the host, not inside a container
./install_udev_rules.sh

# 5.2 Unplug and replug the MANUS dongle

# 5.3 Download the MANUS SDK, then build and install the plugin
./install_manus.sh

cd /path/to/IsaacTeleop
ls -l install/plugins/manus/
ls -l install/bin/manus_hand_tracker_printer

# -----------------------------------------------------------------------------
# 6. Open the ports required for AVP to connect to CloudXR
# -----------------------------------------------------------------------------

sudo ufw allow 48010,48322/tcp
sudo ufw allow 47998:48000,48005,48008,48012/udp

# -----------------------------------------------------------------------------
# 7. Terminal A: start the CloudXR runtime
# -----------------------------------------------------------------------------

cd /path/to/IsaacTeleop
conda activate isaacteleop

echo 'NV_DEVICE_PROFILE=auto-native' > custom.env
python -m isaacteleop.cloudxr --cloudxr-env-config=./custom.env --accept-eula

# Keep terminal A running.

# -----------------------------------------------------------------------------
# 8. Check the local IP address and connect from the AVP device
# -----------------------------------------------------------------------------


# Manual steps on the AVP side:
# 1. Open Isaac XR Teleop Sample Client (version 3.0.0 or newer).
# 2. Enter the Ubuntu LAN IP address found above.
# 3. Connect and keep the session alive.

# -----------------------------------------------------------------------------
# 9. Terminal B: load the CloudXR environment and verify MANUS data first
# -----------------------------------------------------------------------------

cd /path/to/IsaacTeleop
source ~/.cloudxr/run/cloudxr.env

./install/bin/manus_hand_tracker_printer

# Once hand data and the visualization window are updating correctly, close
# `manus_hand_tracker_printer`.
# Note: the MANUS SDK can only be owned by one process at a time, so the
# printer must be closed before starting the main demo.

# -----------------------------------------------------------------------------
# 10. Terminal C: run the final demo
# -----------------------------------------------------------------------------

cd /path/to/IsaacTeleop
source ~/.cloudxr/run/cloudxr.env
conda activate isaacteleop
python examples/g1_wuji_teleop/scripts/g1_wuji_teleop_main.py \
    --config /examples/g1_wuji_teleop/config/avp_manus.yml \
    --device cuda:0 \
    --viz kit
