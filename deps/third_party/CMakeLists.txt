# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

include(FetchContent)

# ==============================================================================
# OpenXR SDK
# ==============================================================================
# Fetch OpenXR SDK from GitHub (using the same commit as the old submodule)
message(STATUS "Fetching OpenXR SDK from GitHub...")
FetchContent_Declare(
    openxr-sdk
    GIT_REPOSITORY https://github.com/KhronosGroup/OpenXR-SDK.git
    GIT_TAG        75c53b6e853dc12c7b3c771edc9c9c841b15faaa  # release-1.1.53
    GIT_SHALLOW    FALSE  # Need full history for this specific commit
)

# Build OpenXR loader as a static library to avoid runtime dependency issues
set(DYNAMIC_LOADER OFF CACHE BOOL "Build OpenXR loader as static library" FORCE)

FetchContent_MakeAvailable(openxr-sdk)
message(STATUS "Building OpenXR SDK from FetchContent (static library)")

# ==============================================================================
# yaml-cpp
# ==============================================================================
# yaml-cpp is used for parsing YAML configuration files
# Build as a static library to avoid runtime dependency issues
message(STATUS "Fetching yaml-cpp from GitHub...")
FetchContent_Declare(
    yaml-cpp
    GIT_REPOSITORY https://github.com/jbeder/yaml-cpp.git
    GIT_TAG        f7320141120f720aecc4c32be25586e7da9eb978  # 0.8.0
    GIT_SHALLOW    FALSE  # Need full history for this specific commit
)

# Configure yaml-cpp build options
set(YAML_CPP_BUILD_TESTS OFF CACHE BOOL "Enable testing" FORCE)
set(YAML_CPP_BUILD_TOOLS OFF CACHE BOOL "Enable parse tools" FORCE)
set(YAML_CPP_BUILD_CONTRIB OFF CACHE BOOL "Enable contrib stuff in library" FORCE)
set(YAML_CPP_INSTALL OFF CACHE BOOL "Enable generation of install target" FORCE)
set(YAML_BUILD_SHARED_LIBS OFF CACHE BOOL "Build yaml-cpp as shared library" FORCE)

FetchContent_MakeAvailable(yaml-cpp)
message(STATUS "Building yaml-cpp from FetchContent (static library)")

# ==============================================================================
# pybind11
# ==============================================================================
# pybind11 is used for Python bindings (header-only library)
# Only add if Python bindings are enabled
if(BUILD_PYTHON_BINDINGS)
    message(STATUS "Fetching pybind11 from GitHub...")
    FetchContent_Declare(
        pybind11
        GIT_REPOSITORY https://github.com/pybind/pybind11.git
        GIT_TAG        a2e59f0e7065404b44dfe92a28aca47ba1378dc4  # v2.11.0-182
        GIT_SHALLOW    FALSE  # Need full history for this specific commit
    )
    
    FetchContent_MakeAvailable(pybind11)
    message(STATUS "Using pybind11 from FetchContent")
    
    # Verify pybind11 targets are available
    if(NOT TARGET pybind11::module)
        message(FATAL_ERROR "pybind11::module target not found after FetchContent")
    endif()
endif()

