# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# ==============================================================================
# Schema library (isaacteleop_schema)
# ==============================================================================
# Generates C++ headers from the module's FlatBuffer schemas and exposes them,
# with the FlatBuffers runtime, under the <schema/...> prefix.

include(${CMAKE_SOURCE_DIR}/cmake/GenerateFlatBuffers.cmake)

generate_flatbuffer_headers(
  SCHEMA_GENERATED_HEADERS
  ${SCHEMA_FBS_DIR}
  ${CMAKE_CURRENT_BINARY_DIR}/generated/schema
)

add_custom_target(schema_header_generation
  DEPENDS ${SCHEMA_GENERATED_HEADERS}
)

add_library(isaacteleop_schema INTERFACE)
add_dependencies(isaacteleop_schema schema_header_generation)

target_include_directories(isaacteleop_schema INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated>
  # Hand-written companion headers (e.g. deprecated back-compat aliases), reached as <schema/...>.
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(isaacteleop_schema INTERFACE
  flatbuffers
)
