# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20...3.25)

# Workaround for older CMake policy compatibility in dependencies
set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "Minimum CMake policy version")

include(cmake/IsaacTeleopVersion.cmake)
isaac_teleop_read_version("${CMAKE_CURRENT_SOURCE_DIR}/VERSION" ISAAC_TELEOP_VERSION ISAAC_TELEOP_PYPROJECT_VERSION)

# ==============================================================================
# Install Prefix Setup (must be before HunterGate)
# ==============================================================================
# Set default install prefix early, before HunterGate which may affect
# CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT
if(NOT DEFINED CMAKE_INSTALL_PREFIX OR CMAKE_INSTALL_PREFIX STREQUAL "" OR CMAKE_INSTALL_PREFIX MATCHES "^/usr/local")
    set(CMAKE_INSTALL_PREFIX "${CMAKE_CURRENT_SOURCE_DIR}/install" CACHE PATH "Install prefix" FORCE)
endif()
# ==============================================================================

# HunterGate Setup (must be before project())
# Defines BUILD_PLUGINS option and initializes Hunter for DepthAI dependencies
include(cmake/SetupHunter.cmake)

project(IsaacTeleop VERSION ${ISAAC_TELEOP_VERSION} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ==============================================================================
# Python Version Configuration (SINGLE SOURCE OF TRUTH)
# ==============================================================================
# All Python-related configurations should reference this variable.
# To change the Python version, only modify this line:
set(ISAAC_TELEOP_PYTHON_VERSION "3.11" CACHE STRING "Python version for Isaac Teleop")
message(STATUS "Configuring for Python ${ISAAC_TELEOP_PYTHON_VERSION}")
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
    add_subdirectory(examples/schemaio)
    add_subdirectory(examples/xdev_list)
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
