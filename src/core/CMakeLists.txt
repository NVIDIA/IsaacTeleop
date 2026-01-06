# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Options
option(BUILD_PYTHON_BINDINGS "Build Python bindings" ON)

# Generated headers from FlatBuffer schemas with additional utilities.
add_subdirectory(schema)

# Build OXR Utils first - header-only utilities (no dependencies)
add_subdirectory(oxr_utils)

# Build Plugin Manager
add_subdirectory(plugin_manager)

# Build OXR library (depends on oxr_utils for types)
add_subdirectory(oxr)

# Build MCAP library first (only needs deviceio headers for tracker interface)
add_subdirectory(mcap)

# Build DEVICEIO library (depends on oxr_utils for types, links to mcap_core)
add_subdirectory(deviceio)

# Python wheel packaging (combines both modules)
if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()

# Unit tests using Catch2.
if(BUILD_TESTING)
  add_subdirectory(schema_tests/cpp)
  add_subdirectory(mcap_tests/cpp)
endif()