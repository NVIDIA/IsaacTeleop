# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# ==============================================================================
# FlatBuffer Schema Generation
# ==============================================================================
# Generate C++ headers from FlatBuffer schema files.

include(${CMAKE_SOURCE_DIR}/cmake/GenerateFlatBuffers.cmake)

# Generate headers from schemas.
generate_flatbuffer_headers(
  SCHEMA_GENERATED_HEADERS
  ${CMAKE_CURRENT_SOURCE_DIR}/fbs
  ${CMAKE_CURRENT_BINARY_DIR}/generated/schema
)

# Create a custom target for header generation.
add_custom_target(schema_header_generation
  DEPENDS ${SCHEMA_GENERATED_HEADERS}
)

# ==============================================================================
# Schema Library
# ==============================================================================
# Library containing generated FlatBuffer schema types.

add_library(teleopcore_schema INTERFACE)
add_dependencies(teleopcore_schema schema_header_generation)

# Include directories for generated headers and FlatBuffers runtime.
target_include_directories(teleopcore_schema INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/cpp/inc>
)

# Link FlatBuffers runtime (target created by FetchContent in deps/third_party).
target_link_libraries(teleopcore_schema INTERFACE
  flatbuffers
)

message(STATUS "TeleopCore schema library configured with FlatBuffer")
