# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20...3.25)

# Workaround for older CMake policy compatibility in dependencies
set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "Minimum CMake policy version")

# ==============================================================================
# Version Configuration (SINGLE SOURCE OF TRUTH)
# ==============================================================================
# Read version from VERSION file - this is the single source of truth for the
# TeleopCore version. Both CMake and Python (pyproject.toml) read from this file.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/VERSION" TELEOPCORE_VERSION)
string(STRIP "${TELEOPCORE_VERSION}" TELEOPCORE_VERSION)
message(STATUS "TeleopCore version: ${TELEOPCORE_VERSION}")
# ==============================================================================

# ==============================================================================
# Install Prefix Setup (must be before HunterGate)
# ==============================================================================
# Set default install prefix early, before HunterGate which may affect
# CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT
if(NOT DEFINED CMAKE_INSTALL_PREFIX OR CMAKE_INSTALL_PREFIX STREQUAL "" OR CMAKE_INSTALL_PREFIX MATCHES "^/usr/local")
    set(CMAKE_INSTALL_PREFIX "${CMAKE_CURRENT_SOURCE_DIR}/install" CACHE PATH "Install prefix" FORCE)
endif()
# ==============================================================================

# ==============================================================================
# HunterGate Setup (must be before project())
# ==============================================================================
# Required for DepthAI plugin. Hunter is initialized here so that when DepthAI
# is added via FetchContent, it reuses our Hunter configuration.
option(BUILD_PLUGINS "Build plugins" ON)
if(BUILD_PLUGINS)
    # Set variables needed by Hunter config for DepthAI dependencies
    option(DEPTHAI_ENABLE_LIBUSB "Enable libusb for DepthAI" ON)
    if(WIN32)
        set(DEPTHAI_CURL_USE_SCHANNEL ON)
        set(DEPTHAI_CURL_USE_OPENSSL OFF)
    else()
        set(DEPTHAI_CURL_USE_SCHANNEL OFF)
        set(DEPTHAI_CURL_USE_OPENSSL ON)
    endif()

    # Download HunterGate.cmake from GitHub if not present or empty
    set(HUNTERGATE_VERSION "v0.11.0")
    set(HUNTERGATE_SHA1 "c581aaacda7fee2e4586adf39084f24709b8e51f")
    set(HUNTERGATE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake/HunterGate.cmake")

    set(_huntergate_need_download FALSE)
    if(NOT EXISTS "${HUNTERGATE_PATH}")
        set(_huntergate_need_download TRUE)
    else()
        file(SIZE "${HUNTERGATE_PATH}" _huntergate_size)
        if(_huntergate_size EQUAL 0)
            file(REMOVE "${HUNTERGATE_PATH}")
            set(_huntergate_need_download TRUE)
        endif()
    endif()

    if(_huntergate_need_download)
        message(STATUS "Downloading HunterGate.cmake ${HUNTERGATE_VERSION}...")
        file(DOWNLOAD
            "https://raw.githubusercontent.com/cpp-pm/gate/${HUNTERGATE_VERSION}/cmake/HunterGate.cmake"
            "${HUNTERGATE_PATH}"
            EXPECTED_HASH SHA1=${HUNTERGATE_SHA1}
            STATUS huntergate_download_status
            TLS_VERIFY ON
        )
        list(GET huntergate_download_status 0 huntergate_status_code)
        list(GET huntergate_download_status 1 huntergate_status_msg)
        if(NOT huntergate_status_code EQUAL 0)
            file(REMOVE "${HUNTERGATE_PATH}")  # Clean up failed download
            message(FATAL_ERROR "Failed to download HunterGate.cmake: ${huntergate_status_msg}")
        endif()
        message(STATUS "HunterGate.cmake downloaded successfully")
    endif()

    # Download DepthAI Hunter config from GitHub if not present or empty
    set(DEPTHAI_VERSION "v2.29.0")
    set(DEPTHAI_CONFIG_SHA1 "a88698ab81b7edef79a2446edcf649dc92cddcbc")
    set(DEPTHAI_CONFIG_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake/Hunter/config-depthai.cmake")

    set(_depthai_config_need_download FALSE)
    if(NOT EXISTS "${DEPTHAI_CONFIG_PATH}")
        set(_depthai_config_need_download TRUE)
    else()
        file(SIZE "${DEPTHAI_CONFIG_PATH}" _depthai_config_size)
        if(_depthai_config_size EQUAL 0)
            file(REMOVE "${DEPTHAI_CONFIG_PATH}")
            set(_depthai_config_need_download TRUE)
        endif()
    endif()

    if(_depthai_config_need_download)
        message(STATUS "Downloading Hunter config for DepthAI ${DEPTHAI_VERSION}...")
        file(DOWNLOAD
            "https://raw.githubusercontent.com/luxonis/depthai-core/${DEPTHAI_VERSION}/cmake/Hunter/config.cmake"
            "${DEPTHAI_CONFIG_PATH}"
            EXPECTED_HASH SHA1=${DEPTHAI_CONFIG_SHA1}
            STATUS depthai_config_download_status
            TLS_VERIFY ON
        )
        list(GET depthai_config_download_status 0 depthai_config_status_code)
        list(GET depthai_config_download_status 1 depthai_config_status_msg)
        if(NOT depthai_config_status_code EQUAL 0)
            file(REMOVE "${DEPTHAI_CONFIG_PATH}")  # Clean up failed download
            message(FATAL_ERROR "Failed to download DepthAI Hunter config: ${depthai_config_status_msg}")
        endif()
        message(STATUS "DepthAI Hunter config downloaded successfully")
    endif()

    include("${HUNTERGATE_PATH}")

    # Set CMAKE_POLICY_VERSION_MINIMUM as environment variable so it's inherited
    # by all child CMake processes (Hunter ExternalProject builds)
    # This fixes compatibility with CMake >= 4.0 for packages with old cmake_minimum_required
    set(ENV{CMAKE_POLICY_VERSION_MINIMUM} "3.5")

    HunterGate(
        URL "https://github.com/cpp-pm/hunter/archive/9d9242b60d5236269f894efd3ddd60a9ca83dd7f.tar.gz"
        SHA1 "16cc954aa723bccd16ea45fc91a858d0c5246376"
        LOCAL  # Uses cmake/Hunter/config.cmake
    )
endif()
# ==============================================================================

project(TeleopCore VERSION ${TELEOPCORE_VERSION} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ==============================================================================
# Python Version Configuration (SINGLE SOURCE OF TRUTH)
# ==============================================================================
# All Python-related configurations should reference this variable.
# To change the Python version, only modify this line:
set(TELEOPCORE_PYTHON_VERSION "3.11" CACHE STRING "Python version for TeleopCore")
# ==============================================================================

# Configure Python via uv BEFORE any dependencies are added
# This ensures all subdirectories (including openxr-sdk) use the managed Python
include(cmake/SetupPython.cmake)

# Set default build type to Release if not specified
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Note: CMAKE_INSTALL_PREFIX is set early (before HunterGate) to avoid issues
# with CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT being affected by Hunter's
# internal project() call.

# Options
option(BUILD_EXAMPLES "Build examples" ON)
option(BUILD_PYTHON_BINDINGS "Build Python bindings" ON)
# Note: BUILD_PLUGINS is defined before project() for HunterGate initialization
option(BUILD_TESTING "Build unit tests" ON)
option(ENABLE_EXPERIMENTAL_WINDOWS_BUILD "Enable experimental Windows build support (source code only)" OFF)
## Enforce clang-format on Linux builds by default
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(_clang_default ON)
else()
    set(_clang_default OFF)
endif()
option(ENABLE_CLANG_FORMAT_CHECK "Fail build if clang-format changes would be applied (Linux default ON)" ${_clang_default})

# Windows support warning
if(WIN32)
    if(NOT ENABLE_EXPERIMENTAL_WINDOWS_BUILD)
        message(FATAL_ERROR
            "================================================================================\n"
            "Windows is not officially supported!\n"
            "If you want to build anyway for development/testing purposes, add:\n"
            "  -DENABLE_EXPERIMENTAL_WINDOWS_BUILD=ON\n"
            "Use at your own risk!\n"
            "================================================================================\n"
        )
    else()
        # Create a function to print the warning cleanly
        function(print_windows_warning)
            message(STATUS "")
            message(STATUS "================================================================================")
            message(STATUS "⚠️  EXPERIMENTAL WINDOWS BUILD ENABLED - USE AT YOUR OWN RISK ⚠️")
            message(STATUS "")
            message(STATUS "You have enabled experimental Windows build support.")
            message(STATUS "The source code will compile but there is NO guarantee of any functionality.")
            message(STATUS "This is for development and testing purposes only!")
            message(STATUS "================================================================================")
        endfunction()

        # Defer the warning to the end of configuration so it's highly visible
        cmake_language(DEFER CALL print_windows_warning)
    endif()
endif()

# Build dependencies (OpenXR SDK, etc.)
add_subdirectory(deps)

# Enable CTest at top level so tests from subdirectories are discoverable
if(BUILD_TESTING)
    # Make sure to call this after `deps` is added so that Catch2 is available
    enable_testing()
endif()

# Build interfaces (headers)
add_subdirectory(deps/cloudxr/openxr_extensions)

# Build core modules (OXR and DEVICEIO)
add_subdirectory(src/core)

# Build examples if requested
if(BUILD_EXAMPLES)
    add_subdirectory(examples/oxr)
    add_subdirectory(examples/retargeting)
    add_subdirectory(examples/teleop_session_manager)
endif()

# Build plugins if requested
if(BUILD_PLUGINS)
    # Build plugin utilities
    add_subdirectory(src/plugins/plugin_utils)

    add_subdirectory(src/plugins/controller_synthetic_hands)
    add_subdirectory(src/plugins/manus)
    add_subdirectory(src/plugins/oakd)
endif()

# Formatting enforcement (runs on Linux by default)
include(cmake/ClangFormat.cmake)
