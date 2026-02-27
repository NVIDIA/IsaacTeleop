# syntax=docker/dockerfile:1
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Build for Jazzy: --build-arg ROS_DISTRO=jazzy --build-arg PYTHON_VERSION=3.12
ARG ROS_DISTRO=humble
ARG PYTHON_VERSION=3.10

# -----------------------------------------------------------------------------
# Base: common runtime deps + uv + Python (shared by builder and runtime)
# -----------------------------------------------------------------------------
FROM ros:${ROS_DISTRO}-ros-base AS base
ARG ROS_DISTRO
ARG PYTHON_VERSION

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
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

# Install uv via standalone script (avoids PEP 668 "externally managed" pip on Ubuntu 24.04 / Jazzy)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv

RUN uv python install ${PYTHON_VERSION} --quiet \
    && uv python find ${PYTHON_VERSION}

# -----------------------------------------------------------------------------
# Stage 1: build and install
# -----------------------------------------------------------------------------
FROM base AS builder
ARG ROS_DISTRO
ARG PYTHON_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    clang-format \
    cmake \
    git \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/isaacteleop
COPY . /opt/isaacteleop

RUN --mount=type=cache,target=/opt/isaacteleop/build,id=isaacteleop-teleop-ros2-build-${ROS_DISTRO} \
    cmake -B build -S . \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/isaacteleop/install \
        -DBUILD_EXAMPLES=OFF \
        -DBUILD_EXAMPLE_TELEOP_ROS2=ON \
        -DBUILD_TESTING=OFF \
        -DBUILD_PLUGINS=ON \
        -DBUILD_PLUGIN_OAK_CAMERA=OFF \
        -DENABLE_CLANG_FORMAT_CHECK=OFF \
        -DISAAC_TELEOP_PYTHON_VERSION=${PYTHON_VERSION} \
    && cmake --build build --config Release -j$(nproc) \
    && cmake --install build --config Release

COPY --chmod=644 <<EOF /usr/local/bin/teleop-env-setup
source /opt/ros/${ROS_DISTRO}/setup.bash
EOF

COPY --chmod=755 <<'EOF' /usr/local/bin/teleop-entrypoint
#!/bin/bash
set -e
source /usr/local/bin/teleop-env-setup
exec "$@"
EOF

# -----------------------------------------------------------------------------
# Stage 2: runtime image (install tree only)
# -----------------------------------------------------------------------------
FROM base

COPY --from=builder /opt/isaacteleop/install /opt/isaacteleop/install
COPY --from=builder /usr/local/bin/teleop-env-setup /usr/local/bin/teleop-env-setup
COPY --from=builder /usr/local/bin/teleop-entrypoint /usr/local/bin/teleop-entrypoint

ENV ISAAC_TELEOP_PLUGIN_PATH=/opt/isaacteleop/install/plugins
ENV BASH_ENV=/usr/local/bin/teleop-env-setup

RUN echo "source /usr/local/bin/teleop-env-setup" >> /etc/bash.bashrc

WORKDIR /opt/isaacteleop/install/examples/teleop_ros2/python

# Pre-install Python dependencies so uv run doesn't download at every launch.
RUN uv sync --no-dev

ENTRYPOINT ["/usr/local/bin/teleop-entrypoint", "uv", "run", "teleop_ros2_publisher.py"]
