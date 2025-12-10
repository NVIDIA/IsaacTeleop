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
  MESSAGES_GENERATED_HEADERS
  ${CMAKE_CURRENT_SOURCE_DIR}/schemas
  ${CMAKE_CURRENT_BINARY_DIR}/generated/core/messages
)

# Create a custom target for header generation.
add_custom_target(messages_header_generation
  DEPENDS ${MESSAGES_GENERATED_HEADERS}
)

# ==============================================================================
# Messages Library
# ==============================================================================
# Library containing generated FlatBuffer message types.

add_library(teleopcore_messages INTERFACE)
add_library(teleopcore::messages ALIAS teleopcore_messages)

add_dependencies(teleopcore_messages messages_header_generation)

# Include directories for generated headers and FlatBuffers runtime.
target_include_directories(teleopcore_messages INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated>
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/schemas>
)

# Link FlatBuffers runtime (target created by FetchContent in deps/third_party).
target_link_libraries(teleopcore_messages INTERFACE
  flatbuffers
)

message(STATUS "TeleopCore messages library configured with FlatBuffer schemas")

# ==============================================================================
# Tensor Unit Tests
# ==============================================================================
# Unit tests for FlatBuffer message types using Catch2.

if(BUILD_TESTING)
  add_subdirectory(tests)
endif()
