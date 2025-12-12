# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# ==============================================================================
# Schema Library (C++ utilities)
# ==============================================================================
# Library containing generated FlatBuffer schema types.

add_library(teleopcore_schema INTERFACE)
add_dependencies(teleopcore_schema schema_header_generation)

# Include directories for generated headers and FlatBuffers runtime.
target_include_directories(teleopcore_schema INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/../fbs/generated>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# Link FlatBuffers runtime (target created by FetchContent in deps/third_party).
target_link_libraries(teleopcore_schema INTERFACE
  flatbuffers
)
