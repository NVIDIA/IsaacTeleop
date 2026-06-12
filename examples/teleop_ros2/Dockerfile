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
ARG TARGETARCH

# Compiler cache. CCACHE_DIR points at a BuildKit cache mount kept on the
# runner's local BuildKit storage (not the image, not GitHub Actions cache),
# so unchanged translation units are reused across builds. Bounded so it
# self-evicts LRU instead of growing without limit.
ENV CCACHE_DIR=/ccache CCACHE_MAXSIZE=5G

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ccache \
    clang-format \
    cmake \
    git \
    patchelf \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/isaacteleop
COPY . /opt/isaacteleop

# Remove any install/ or build/ copied in from the host context (an extracted
# build-ubuntu artifact tree can carry both). A stale install/wheels/ would
# pollute find-links with an isaacteleop wheel that is not the one this build
# produces; a stale build/ would skip a clean CMake reconfigure. The build tree
# is rebuilt from scratch every time -- ccache keeps recompiles cheap -- so each
# build reconfigures against the current image rather than trusting cached
# configure results.
RUN --mount=type=cache,target=/ccache,id=isaacteleop-teleop-ros2-ccache-${ROS_DISTRO}-${TARGETARCH} \
    rm -rf /opt/isaacteleop/install /opt/isaacteleop/build \
    && cmake -B build -S . \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/isaacteleop/install \
        -DCMAKE_C_COMPILER_LAUNCHER=ccache \
        -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
        -DBUILD_EXAMPLES=OFF \
        -DBUILD_EXAMPLE_TELEOP_ROS2=ON \
        -DBUILD_TESTING=OFF \
        -DBUILD_PLUGINS=ON \
        -DBUILD_PLUGIN_OAK_CAMERA=OFF \
        -DENABLE_CLANG_FORMAT_CHECK=OFF \
        -DENABLE_CLOUDXR_BUNDLE_CHECK=ON \
        -DBUNDLE_ROBOTIC_GROUNDING=${BUNDLE_ROBOTIC_GROUNDING} \
        -DISAAC_TELEOP_PYTHON_VERSION=${PYTHON_VERSION} \
    && cmake --build build --config Release -j$(nproc) \
    && cmake --install build --config Release \
    && ccache --show-stats

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

# The node launches the CloudXR runtime in-process via CloudXRLauncher, so this
# image needs GPU access and the NVIDIA Vulkan/EGL ICDs. Run with --gpus all.
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=all
RUN mkdir -p /etc/vulkan/icd.d /usr/share/glvnd/egl_vendor.d
COPY deps/cloudxr/runtime/data/10_nvidia.json /usr/share/glvnd/egl_vendor.d/
COPY deps/cloudxr/runtime/data/nvidia_icd.json /etc/vulkan/icd.d/
ENV VK_DRIVER_FILES=/etc/vulkan/icd.d/nvidia_icd.json

COPY --from=nlopt_wheel /opt/nlopt-wheels /opt/nlopt-wheels

# Pre-install heavy Python dependencies so they are cached independently of C++ builds.
# Copy requirements from the context, avoiding any files from the 'builder' stage.
COPY src/core/python/requirements.txt \
     src/core/python/requirements-retargeters.txt \
     src/core/python/requirements-grounding.txt \
     src/core/python/requirements-cloudxr.txt \
     /tmp/
RUN uv venv --python=${PYTHON_VERSION} && \
    uv pip install setuptools wheel && \
    uv pip install --find-links=/opt/nlopt-wheels --no-build-isolation-package nlopt \
        -r /tmp/requirements.txt \
        -r /tmp/requirements-retargeters.txt \
        -r /tmp/requirements-grounding.txt \
        -r /tmp/requirements-cloudxr.txt \
        msgpack msgpack-numpy && \
    rm /tmp/requirements.txt \
       /tmp/requirements-retargeters.txt \
       /tmp/requirements-grounding.txt \
       /tmp/requirements-cloudxr.txt

COPY --from=builder /opt/isaacteleop/install /opt/isaacteleop/install
COPY --from=sharpa_urdfs /opt/sharpa-wave-urdfs/ /opt/isaacteleop/install/examples/teleop_ros2/assets/urdf/sharpa_standalone/
COPY --from=builder /usr/local/bin/teleop-env-setup /usr/local/bin/teleop-env-setup
COPY --from=builder /usr/local/bin/teleop-entrypoint /usr/local/bin/teleop-entrypoint

ENV ISAAC_TELEOP_PLUGIN_PATH=/opt/isaacteleop/install/plugins
ENV BASH_ENV=/usr/local/bin/teleop-env-setup

RUN echo "source /usr/local/bin/teleop-env-setup" >> /etc/bash.bashrc

# Pre-install Python dependencies so uv run doesn't download at every launch.
# Pin isaacteleop to the exact version of the locally-built wheel so the
# resolver cannot prefer a published PyPI release (whose dep metadata may
# diverge from what this image was actually built with). Extract the version
# from the wheel filename rather than hard-coding it.
RUN set -eu; \
    echo "== isaacteleop wheels found in find-links =="; \
    ls -la /opt/isaacteleop/install/wheels/ || true; \
    wheels=$(ls /opt/isaacteleop/install/wheels/isaacteleop-*.whl 2>/dev/null); \
    count=$(printf '%s\n' "$wheels" | grep -c .); \
    if [ "$count" -ne 1 ]; then \
        echo "ERROR: expected exactly 1 isaacteleop wheel in find-links, found $count:"; \
        printf '  %s\n' $wheels; \
        exit 1; \
    fi; \
    wheel=$wheels; \
    version=$(basename "$wheel" | sed -E 's/^isaacteleop-([^-]+)-.*$/\1/'); \
    echo "== pinning isaacteleop==${version} =="; \
    uv sync --no-dev --find-links=/opt/nlopt-wheels --upgrade-package "isaacteleop==${version}"

# Use --no-sync because the venv is already provisioned above, and the implicit
# resync runs without --find-links and fails on aarch64 (no nlopt wheel on PyPI).
ENTRYPOINT ["/usr/local/bin/teleop-entrypoint", "uv", "run", "--no-sync", "teleop_ros2_node.py"]
