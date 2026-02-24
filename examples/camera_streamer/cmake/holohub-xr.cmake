# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# HoloHub XR operator setup for camera_streamer.
#
# Downloads FetchHolohubOperator.cmake from GitHub, then uses it to fetch the
# XR operator and apply patches for OpenXR compatibility, destruction ordering,
# Subgraph support, and CUDA arch auto-detection.

set(HOLOHUB_BRANCH "holoscan-sdk-3.11.0" CACHE STRING "HoloHub branch/tag")

if(TARGET holoscan::ops::xr)
  return()
endif()

# Vulkan is required for the XR operator.
find_package(Vulkan REQUIRED)

# Download FetchHolohubOperator.cmake from HoloHub on GitHub.
set(FETCH_HOLOHUB_OPERATOR_URL
  "https://raw.githubusercontent.com/nvidia-holoscan/holohub/refs/heads/main/cmake/FetchHolohubOperator.cmake")
set(FETCH_HOLOHUB_OPERATOR_LOCAL_PATH
  "${CMAKE_CURRENT_BINARY_DIR}/FetchHolohubOperator.cmake")

if(NOT EXISTS ${FETCH_HOLOHUB_OPERATOR_LOCAL_PATH})
  file(DOWNLOAD
    ${FETCH_HOLOHUB_OPERATOR_URL}
    ${FETCH_HOLOHUB_OPERATOR_LOCAL_PATH}
    SHOW_PROGRESS
    TLS_VERIFY ON
  )
  if(NOT EXISTS ${FETCH_HOLOHUB_OPERATOR_LOCAL_PATH})
    message(FATAL_ERROR
      "Failed to download FetchHolohubOperator.cmake from ${FETCH_HOLOHUB_OPERATOR_URL}")
  endif()
endif()

include(${FETCH_HOLOHUB_OPERATOR_LOCAL_PATH})

set(_PATCH_DIR "${CMAKE_CURRENT_LIST_DIR}/patches")

fetch_holohub_operator(xr
  REPO_URL https://github.com/nvidia-holoscan/holohub.git
  BRANCH   ${HOLOHUB_BRANCH}
  PATCH_COMMAND
    /bin/sh -c
      "git apply --reject ${_PATCH_DIR}/fix-xr-xrsession-openxr-version.patch || true && \
       git apply --reject ${_PATCH_DIR}/fix-xr-session-destruction-order.patch || true && \
       git apply --reject ${_PATCH_DIR}/fix-xr-cuda-arch-native.patch || true"
)
