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
    GIT_TAG        bbf8bdb087bb3f3621ca0a5ace06047805f4e9f3  # master as of Dec 1, 2025
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

# ==============================================================================
# FlatBuffers
# ==============================================================================
# FlatBuffers is used for efficient serialization of messages.
FetchContent_Declare(
    flatbuffers
    GIT_REPOSITORY https://github.com/google/flatbuffers.git
    GIT_TAG v24.3.25
)

# Configure FlatBuffers build options.
set(FLATBUFFERS_BUILD_TESTS OFF CACHE BOOL "Enable FlatBuffers tests" FORCE)
set(FLATBUFFERS_INSTALL OFF CACHE BOOL "Enable FlatBuffers install" FORCE)
set(FLATBUFFERS_BUILD_FLATC ON CACHE BOOL "Build flatc compiler" FORCE)

FetchContent_MakeAvailable(flatbuffers)
message(STATUS "FlatBuffers fetched and configured")

# ==============================================================================
# Catch2 (Testing Framework)
# ==============================================================================
# Catch2 is a modern, C++-native, test framework for unit tests.
# Only fetch if testing is enabled.
if(BUILD_TESTING)
    message(STATUS "Fetching Catch2 from GitHub...")
    FetchContent_Declare(
        Catch2
        GIT_REPOSITORY https://github.com/catchorg/Catch2.git
        GIT_TAG        v3.11.0
        GIT_SHALLOW    TRUE
    )

    FetchContent_MakeAvailable(Catch2)
    message(STATUS "Catch2 fetched and configured")

    # Make Catch2's CMake modules available for catch_discover_tests
    list(APPEND CMAKE_MODULE_PATH ${Catch2_SOURCE_DIR}/extras)

    include(CTest)
    include(Catch)
endif()

# ==============================================================================
# MCAP (Recording Format Library)
# ==============================================================================
# MCAP is a modular container format for heterogeneous timestamped data.
# It is a header-only library.
message(STATUS "Fetching MCAP from GitHub...")
FetchContent_Declare(
    mcap
    GIT_REPOSITORY https://github.com/foxglove/mcap.git
    GIT_TAG        releases/cpp/v1.4.1
    GIT_SHALLOW    TRUE
)

FetchContent_MakeAvailable(mcap)
message(STATUS "MCAP fetched")

# Create an interface library for MCAP (header-only)
add_library(mcap_interface INTERFACE)
target_include_directories(mcap_interface INTERFACE
    ${mcap_SOURCE_DIR}/cpp/mcap/include
)
# Disable compression to avoid Zstd/LZ4 dependencies
target_compile_definitions(mcap_interface INTERFACE
    MCAP_COMPRESSION_NO_ZSTD
    MCAP_COMPRESSION_NO_LZ4
)
add_library(mcap::mcap ALIAS mcap_interface)
message(STATUS "MCAP interface library configured")
