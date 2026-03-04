# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Camera Streamer: Robot camera streaming and XR visualization operators.
#
# Build modes:
#   Standalone (default):
#     cmake -DBUILD_ENCODER=ON -DBUILD_DECODER=OFF \
#           -DPYTHON_LIB_OUTPUT_DIR=/app/lib ..
#
#   With XR (requires HoloHub XR in Docker image):
#     cmake -DBUILD_XR=ON ..

cmake_minimum_required(VERSION 3.22)
project(camera_streamer LANGUAGES CXX CUDA)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Build options.
option(BUILD_ENCODER "Build NvStreamEncoderOp" ON)
option(BUILD_DECODER "Build NvStreamDecoderOp" ON)
option(BUILD_XR "Build XR plane renderer (requires HoloHub XR)" ON)

# Output directory for Python extension modules (.so).
set(PYTHON_LIB_OUTPUT_DIR "${CMAKE_BINARY_DIR}/python/lib"
    CACHE PATH "Output directory for Python extension modules")

# Find Holoscan SDK.
find_package(holoscan REQUIRED CONFIG
  PATHS "/opt/nvidia/holoscan" "$ENV{HOLOSCAN_SDK_PATH}"
)
message(STATUS "Holoscan SDK: ${holoscan_DIR}")

# XR support: fetch HoloHub XR operator and its dependencies.
if(BUILD_XR)
  list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
  include(holohub-xr)
endif()

# Build C++ operators.
add_subdirectory(operators)
