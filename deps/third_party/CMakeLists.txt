# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# ==============================================================================
# OpenXR SDK
# ==============================================================================
# Always build OpenXR SDK from submodule
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/openxr-sdk/CMakeLists.txt")
    message(FATAL_ERROR "OpenXR SDK submodule not found. Please run: git submodule update --init --recursive")
endif()

# Build OpenXR loader as a static library to avoid runtime dependency issues
set(DYNAMIC_LOADER OFF CACHE BOOL "Build OpenXR loader as static library" FORCE)
add_subdirectory(openxr-sdk)
message(STATUS "Building OpenXR SDK from submodule (static library)")

# ==============================================================================
# pybind11
# ==============================================================================
# pybind11 is used for Python bindings (header-only library)
# Only add if Python bindings are enabled
# Always use the submodule version for consistency
if(BUILD_PYTHON_BINDINGS)
    # Use pybind11 from git submodule
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/pybind11/CMakeLists.txt")
        message(FATAL_ERROR 
            "pybind11 submodule not found. Please initialize it with:\n"
            "  git submodule update --init --recursive")
    endif()
    
    # Add pybind11 subdirectory (header-only, creates pybind11 targets)
    add_subdirectory(pybind11)
    message(STATUS "Using pybind11 from submodule: ${CMAKE_CURRENT_SOURCE_DIR}/pybind11")
    
    # Verify pybind11 targets are available
    if(NOT TARGET pybind11::module)
        message(FATAL_ERROR "pybind11::module target not found after setup")
    endif()
endif()

