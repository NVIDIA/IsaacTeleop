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
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

# Install uv via standalone script (avoids PEP 668 "externally managed" pip on Ubuntu 24.04 / Jazzy)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv

RUN uv python install ${PYTHON_VERSION} --quiet \
    && uv python find ${PYTHON_VERSION}

# -----------------------------------------------------------------------------
# Stage 1: build an nlopt wheel for platforms PyPI does not cover
# -----------------------------------------------------------------------------
FROM base AS nlopt_wheel
ARG PYTHON_VERSION
ARG TARGETARCH

WORKDIR /tmp/nlopt-python
RUN mkdir -p /opt/nlopt-wheels && \
    if [ "${TARGETARCH}" = "arm64" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            build-essential \
            cmake \
            git \
            pkg-config \
        && rm -rf /var/lib/apt/lists/* \
        && git clone --depth 1 --branch 2.10.0 https://github.com/DanielBok/nlopt-python.git . \
        && git submodule update --init --recursive \
        && uv venv --python=${PYTHON_VERSION} /tmp/nlopt-wheel-venv \
        && VIRTUAL_ENV=/tmp/nlopt-wheel-venv uv pip install numpy setuptools wheel \
        && /tmp/nlopt-wheel-venv/bin/python setup.py bdist_wheel -d /opt/nlopt-wheels; \
    fi

# -----------------------------------------------------------------------------
# Stage 2: fetch Sharpa Wave URDF assets
# -----------------------------------------------------------------------------
FROM base AS sharpa_urdfs

WORKDIR /tmp/teleop_ros2
COPY examples/teleop_ros2/scripts/fetch_sharpa_wave_urdfs.py scripts/
COPY examples/teleop_ros2/configs/sharpa_wave_left_dexpilot.yml \
     examples/teleop_ros2/configs/sharpa_wave_right_dexpilot.yml \
     configs/
RUN python3 scripts/fetch_sharpa_wave_urdfs.py --output-dir /opt/sharpa-wave-urdfs

# -----------------------------------------------------------------------------
# Stage 3: build and install
# -----------------------------------------------------------------------------
FROM base AS builder
ARG ROS_DISTRO
ARG PYTHON_VERSION
ARG BUNDLE_ROBOTIC_GROUNDING=false

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
        -DBUNDLE_ROBOTIC_GROUNDING=${BUNDLE_ROBOTIC_GROUNDING} \
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
# Stage 4: runtime image (install tree only)
# -----------------------------------------------------------------------------
FROM base
ARG PYTHON_VERSION

WORKDIR /opt/isaacteleop/install/examples/teleop_ros2/python

COPY --from=nlopt_wheel /opt/nlopt-wheels /opt/nlopt-wheels

# Pre-install heavy Python dependencies so they are cached independently of C++ builds.
# Copy requirements from the context, avoiding any files from the 'builder' stage.
COPY src/core/python/requirements.txt \
     src/core/python/requirements-retargeters.txt \
     src/core/python/requirements-grounding.txt \
     /tmp/
RUN uv venv --python=${PYTHON_VERSION} && \
    uv pip install setuptools wheel && \
    uv pip install --find-links=/opt/nlopt-wheels --no-build-isolation-package nlopt \
        -r /tmp/requirements.txt \
        -r /tmp/requirements-retargeters.txt \
        -r /tmp/requirements-grounding.txt \
        msgpack msgpack-numpy && \
    rm /tmp/requirements.txt \
       /tmp/requirements-retargeters.txt \
       /tmp/requirements-grounding.txt

COPY --from=builder /opt/isaacteleop/install /opt/isaacteleop/install
COPY --from=sharpa_urdfs /opt/sharpa-wave-urdfs/ /opt/isaacteleop/install/examples/teleop_ros2/assets/urdf/sharpa_standalone/
COPY --from=builder /usr/local/bin/teleop-env-setup /usr/local/bin/teleop-env-setup
COPY --from=builder /usr/local/bin/teleop-entrypoint /usr/local/bin/teleop-entrypoint

ENV ISAAC_TELEOP_PLUGIN_PATH=/opt/isaacteleop/install/plugins
ENV BASH_ENV=/usr/local/bin/teleop-env-setup

RUN echo "source /usr/local/bin/teleop-env-setup" >> /etc/bash.bashrc

# Pre-install Python dependencies so uv run doesn't download at every launch.
RUN uv sync --no-dev --find-links=/opt/nlopt-wheels

ENTRYPOINT ["/usr/local/bin/teleop-entrypoint", "uv", "run", "teleop_ros2_node.py"]
