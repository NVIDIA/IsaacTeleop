# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Camera streamer operators.
#
# Options (inherited from parent):
#   BUILD_ENCODER - Build nv_stream_encoder (requires NVENC)
#   BUILD_DECODER - Build nv_stream_decoder (requires NVDEC)
#   BUILD_XR      - Build xr_plane_renderer (requires HoloHub XR)

# pybind11 for Python bindings.
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 QUIET)
if(NOT pybind11_FOUND)
  message(STATUS "Fetching pybind11 v2.13.6...")
  include(FetchContent)
  FetchContent_Declare(pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11
    GIT_TAG v2.13.6
    GIT_SHALLOW TRUE
  )
  FetchContent_MakeAvailable(pybind11)
endif()

if(BUILD_DECODER)
  add_subdirectory(nv_stream_decoder)
endif()

if(BUILD_ENCODER)
  add_subdirectory(nv_stream_encoder)
endif()

if(BUILD_XR)
  add_subdirectory(xr_plane_renderer)
endif()
