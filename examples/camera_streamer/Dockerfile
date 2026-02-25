# syntax=docker/dockerfile:1
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

############################################################
# Holoscan Camera Sender
############################################################
# Multi-camera streaming on Jetson (arm64) and x86_64.
#
# Platform selection:
#   arm64 (Jetson Thor):  holoscan v3.11.0 + CUDA 13
#   x86_64 (Ubuntu):      holoscan v3.11.0 + CUDA 12 dGPU
#
# Build:
#   docker build -t camera-sender .
#
# The TARGETARCH build arg is automatically set by BuildKit.

ARG HOLOSCAN_VERSION=v3.11.0

# Pick the right base image per architecture.
ARG BASE_IMG_ARM64=nvcr.io/nvidia/clara-holoscan/holoscan:${HOLOSCAN_VERSION}-cuda13
ARG BASE_IMG_AMD64=nvcr.io/nvidia/clara-holoscan/holoscan:${HOLOSCAN_VERSION}-cuda12-dgpu

############################################################
# Arch-specific FROM targets (BuildKit pattern)
############################################################
FROM ${BASE_IMG_ARM64} AS base-arm64
FROM ${BASE_IMG_AMD64} AS base-amd64

# TARGETARCH is set by Docker BuildKit (amd64 or arm64).
ARG TARGETARCH
FROM base-${TARGETARCH} AS base

USER root
ENV DEBIAN_FRONTEND=noninteractive

############################################################
# System Dependencies
############################################################

RUN apt-get update && apt-get install -y --no-install-recommends \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    python3-gi \
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gstreamer-1.0 \
    usbutils \
    v4l-utils \
    libusb-1.0-0-dev \
    udev \
    kmod \
    build-essential \
    cmake \
    ninja-build \
    libeigen3-dev \
    libxrandr-dev \
    libxxf86vm-dev \
    libxcb-glx0-dev \
    clang-format \
    iputils-ping \
    net-tools \
    wget \
    zstd \
    && rm -rf /var/lib/apt/lists/*

############################################################
# ZED SDK (architecture-dependent)
############################################################

ARG ZED_SDK_MAJOR=5
ARG ZED_SDK_MINOR=1
ARG TARGETARCH

RUN set -e; \
    case "${TARGETARCH}" in \
      arm64) \
        echo "Installing ZED SDK for L4T 38.2 (Jetson Thor)..."; \
        ZED_URL="https://download.stereolabs.com/zedsdk/${ZED_SDK_MAJOR}.${ZED_SDK_MINOR}/l4t38.2/jetsons"; \
        ;; \
      amd64) \
        echo "Installing ZED SDK for Ubuntu x86_64..."; \
        ZED_URL="https://download.stereolabs.com/zedsdk/${ZED_SDK_MAJOR}.${ZED_SDK_MINOR}/cu12/ubuntu24"; \
        ;; \
      *) echo "Unsupported arch: ${TARGETARCH}"; exit 1 ;; \
    esac; \
    wget -q -O /tmp/ZED_SDK_Linux.run "${ZED_URL}" \
    && chmod +x /tmp/ZED_SDK_Linux.run \
    && /tmp/ZED_SDK_Linux.run -- silent skip_drivers skip_cuda skip_od_module \
    && rm -f /tmp/ZED_SDK_Linux.run \
    && python3 /usr/local/zed/get_python_api.py \
    && pip3 install --no-cache-dir --no-deps "numpy==1.26.0" \
    && echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="2b03", MODE="0666"' \
       > /etc/udev/rules.d/99-zed.rules \
    && chmod 644 /etc/udev/rules.d/99-zed.rules \
    && echo "[OK] ZED SDK ${ZED_SDK_MAJOR}.${ZED_SDK_MINOR} installed (${TARGETARCH})"

############################################################
# Python Dependencies
############################################################

ARG TARGETARCH
RUN set -e; \
    case "${TARGETARCH}" in \
      arm64) CUPY_PKG="cupy-cuda13x" ;; \
      amd64) CUPY_PKG="cupy-cuda12x" ;; \
    esac; \
    pip3 install --no-cache-dir pyyaml loguru "${CUPY_PKG}" depthai opencv-python-headless

# udev rules for OAK-D cameras.
RUN echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' \
    > /etc/udev/rules.d/80-movidius.rules \
    && chmod 644 /etc/udev/rules.d/80-movidius.rules

############################################################
# Application Code
############################################################

WORKDIR /camera_streamer

COPY . /camera_streamer/

############################################################
# Environment
############################################################

# Python/lib paths: /camera_streamer/python is for the committed image (deploy),
# /camera_streamer/build/python is for host-mounted dev builds (run-container).
# The /lib subdirectory is for HoloHub's holohub.xr package.
ENV PYTHONPATH="/camera_streamer:\
/camera_streamer/python:/camera_streamer/python/lib:\
/camera_streamer/build/python:/camera_streamer/build/python/lib:\
${PYTHONPATH}"
ENV LD_LIBRARY_PATH="/camera_streamer/python:/camera_streamer/build/python:${LD_LIBRARY_PATH}"

############################################################
# Entrypoint
############################################################

COPY --chmod=755 <<'ENTRY' /usr/local/bin/camera-sender-entrypoint
#!/bin/bash
set -e
if [ "$(id -u)" -eq 0 ] && command -v udevadm >/dev/null 2>&1; then
    if ! pgrep -x udevd > /dev/null 2>&1; then
        mkdir -p /run/udev
        /lib/systemd/systemd-udevd --daemon 2>/dev/null || true
        udevadm trigger 2>/dev/null || true
        udevadm settle 2>/dev/null || true
        sleep 1
    fi
fi
exec "$@"
ENTRY

ENTRYPOINT ["/usr/local/bin/camera-sender-entrypoint"]
CMD ["/bin/bash"]

############################################################
# Labels
############################################################

LABEL org.opencontainers.image.title="Teleop Camera Sender (Holoscan)"
LABEL org.opencontainers.image.description="Multi-camera streaming for teleoperation"
