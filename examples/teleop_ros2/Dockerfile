# syntax=docker/dockerfile:1
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

FROM ros:humble-ros-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    clang-format \
    cmake \
    git \
    pkg-config \
    python3-dev \
    python3-pip \
    libbz2-1.0 \
    libreadline8 \
    libsqlite3-0 \
    libffi8 \
    liblzma5 \
    zlib1g \
    libssl3 \
    libncursesw6 \
    libgdbm6 \
    libnss3 \
    libuuid1 \
    libexpat1 \
    libmpdec3 \
    libusb-1.0-0-dev \
    libudev-dev \
    libvulkan1 \
    libgl1-mesa-dev \
    libegl1-mesa-dev \
    libx11-dev \
    libxrandr-dev \
    libxinerama-dev \
    libxcursor-dev \
    libxi-dev \
    libxext-dev \
    libxrender-dev \
    libxfixes-dev \
    libxxf86vm-dev \
    swig \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir uv

WORKDIR /opt/isaacteleop
COPY . /opt/isaacteleop

RUN uv python install 3.10 --quiet \
    && uv python find 3.10

RUN --mount=type=cache,target=/opt/isaacteleop/build,id=isaacteleop-teleop-ros2-build \
    --mount=type=cache,target=/root/.hunter,id=isaacteleop-hunter \
    cmake -B build -S . \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/isaacteleop/install \
        -DBUILD_EXAMPLES=OFF \
        -DBUILD_TESTING=OFF \
        -DBUILD_PLUGINS=ON \
        -DISAAC_TELEOP_PYTHON_VERSION=3.10 \
    && cmake --build build --config Release \
    && cmake --install build --config Release

ENV ISAAC_TELEOP_PLUGIN_PATH=/opt/isaacteleop/install/plugins

COPY --chmod=644 <<'EOF' /usr/local/bin/teleop-env-setup
source /opt/ros/humble/setup.bash
EOF

COPY --chmod=755 <<'EOF' /usr/local/bin/teleop-entrypoint
#!/bin/bash
set -e
source /usr/local/bin/teleop-env-setup
exec "$@"
EOF

# Set BASH_ENV so non-interactive bash shells automatically source the environment setup.
ENV BASH_ENV=/usr/local/bin/teleop-env-setup

# Ensure interactive bash shells source the environment setup.
RUN echo "source /usr/local/bin/teleop-env-setup" >> /etc/bash.bashrc

WORKDIR /opt/isaacteleop/examples/teleop_ros2/python
RUN uv sync

ENTRYPOINT ["/usr/local/bin/teleop-entrypoint", "uv", "run", "teleop_ros2_publisher.py"]
