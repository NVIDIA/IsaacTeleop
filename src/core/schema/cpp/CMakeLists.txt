# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# ==============================================================================
# Schema library (isaacteleop_schema)
# ==============================================================================
# Generates C++ headers from the module's FlatBuffer schemas and exposes them,
# with the FlatBuffers runtime, under the <schema/...> prefix.

include(${CMAKE_SOURCE_DIR}/cmake/GenerateFlatBuffers.cmake)

set(SCHEMA_BFBS_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated/schema CACHE INTERNAL
    "Directory holding the .bfbs built from ${SCHEMA_FBS_DIR}")

generate_flatbuffer_headers(
  SCHEMA_GENERATED_HEADERS
  ${SCHEMA_FBS_DIR}
  ${SCHEMA_BFBS_DIR}
  SCHEMA_GENERATED_BFBS
)

add_custom_target(schema_header_generation
  DEPENDS ${SCHEMA_GENERATED_HEADERS} ${SCHEMA_GENERATED_BFBS}
)

# Refresh the goldens after an intentional schema change. Adds and overwrites only: a
# golden whose .fbs is gone has to be removed by hand. See README.md.
add_custom_target(schema_golden_update
  COMMAND ${CMAKE_COMMAND} -E copy_if_different ${SCHEMA_GENERATED_BFBS} ${SCHEMA_GOLDEN_DIR}
  DEPENDS schema_header_generation
  COMMENT "Copying the freshly built .bfbs over ${SCHEMA_GOLDEN_DIR}"
  VERBATIM
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
