# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# syntax=docker/dockerfile:1
#
# Build with:
#   git archive --format=tar HEAD | sudo docker build --pull --no-cache \
#     --build-context orbbec_sdk=/absolute/path/to/OrbbecSDK_v2 \
#     -f src/plugins/orbbec/cleanroom/Dockerfile -t isaacteleop-orbbec-cleanroom -
#
# The named context keeps the external SDK out of the Git source archive while
# still making the CMake configuration exercise the exact SDK being delivered.
FROM orbbec_sdk AS sdk

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    ccache \
    clang-format-14 \
    cmake \
    curl \
    ffmpeg \
    git \
    jq \
    libavcodec-dev \
    libavutil-dev \
    libudev-dev \
    libsdl2-dev \
    libswscale-dev \
    libvulkan-dev \
    libwayland-dev \
    libx11-dev \
    libxcursor-dev \
    libxext-dev \
    libxi-dev \
    libxinerama-dev \
    libxkbcommon-dev \
    libxrandr-dev \
    patchelf \
    pkg-config \
    wayland-protocols && \
    rm -rf /var/lib/apt/lists/*

# CMake FetchContent clones public GitHub dependencies. HTTP/1.1 avoids
# intermittent GnuTLS HTTP/2 termination errors seen on some Docker networks.
RUN git config --global http.version HTTP/1.1

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:${PATH}"
ENV UV_CACHE_DIR=/tmp/isaacteleop-uv-cache

COPY --from=sdk / /opt/orbbec-sdk
WORKDIR /workspace
COPY . /workspace

# The CloudXR launcher test requires NVIDIA's separately licensed runtime SDK.
# The clean-room image intentionally contains no CloudXR SDK; CI covers it separately.
# CTest 3.22 needs an explicit job count so it does not consume the following -E option.
RUN cmake -S /workspace -B /workspace/build-orbbec-py3.11 \
      -DISAAC_TELEOP_PYTHON_VERSION=3.11 \
      -DBUILD_VIZ=OFF \
      -DBUILD_PLUGIN_ORBBEC_CAMERA=ON \
      -DORBBEC_SDK_ROOT=/opt/orbbec-sdk && \
    cmake --build /workspace/build-orbbec-py3.11 --parallel && \
    env -u PYTHONPATH -u AMENT_PREFIX_PATH -u COLCON_PREFIX_PATH \
      ctest --test-dir /workspace/build-orbbec-py3.11 --output-on-failure -j "$(nproc)" \
        -E '^cloudxr_test_launcher$' && \
    cmake --install /workspace/build-orbbec-py3.11 --prefix /opt/isaacteleop-install && \
    /opt/isaacteleop-install/plugins/orbbec_camera/camera_plugin_orbbec --help && \
    ldd /opt/isaacteleop-install/plugins/orbbec_camera/camera_plugin_orbbec | \
      grep -E 'libOrbbecSDK.so.2 => /opt/isaacteleop-install/plugins/orbbec_camera/libOrbbecSDK.so.2'
