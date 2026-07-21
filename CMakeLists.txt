# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20...3.25)

# Workaround for older CMake policy compatibility in dependencies
set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "Minimum CMake policy version")

include(cmake/IsaacTeleopVersion.cmake)
isaac_teleop_read_version("${CMAKE_CURRENT_SOURCE_DIR}/VERSION" ISAAC_TELEOP_VERSION ISAAC_TELEOP_PYPROJECT_VERSION)

# ==============================================================================
# Install Prefix Setup
# ==============================================================================
if(NOT DEFINED CMAKE_INSTALL_PREFIX OR CMAKE_INSTALL_PREFIX STREQUAL "" OR CMAKE_INSTALL_PREFIX MATCHES "^/usr/local")
    set(CMAKE_INSTALL_PREFIX "${CMAKE_CURRENT_SOURCE_DIR}/install" CACHE PATH "Install prefix" FORCE)
endif()

# ==============================================================================
# DepthAI vcpkg manifest (OAK camera plugin)
# ==============================================================================
# The OAK camera plugin's vcpkg dependencies come from DepthAI's own vcpkg.json,
# auto-downloaded for the pinned tag, rather than a duplicate manifest tracked
# in this repo. This MUST run before project() so vcpkg picks up the manifest
# when the toolchain loads. Gated on the -D option being passed (it lives in the
# cache before project(); the option() default below applies only when unset).
if(BUILD_PLUGIN_OAK_CAMERA)
    include(cmake/DepthAIVcpkgManifest.cmake)
    isaac_teleop_setup_depthai_vcpkg_manifest()
endif()

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
set(ISAAC_TELEOP_PYTHON_VERSION_MIN "3.10")
set(ISAAC_TELEOP_PYTHON_VERSION_MAX_EXCLUSIVE "3.14")
message(STATUS "Configuring for Python ${ISAAC_TELEOP_PYTHON_VERSION}")
# ==============================================================================

# Configure Python via uv BEFORE any dependencies are added
# This ensures all subdirectories (including openxr-sdk) use the managed Python
include(cmake/SetupPython.cmake)

# Set default build type to Release if not specified
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Options
option(BUILD_PLUGINS "Build plugins" ON)
option(BUILD_PLUGIN_OAK_CAMERA "Build OAK camera plugin (requires vcpkg for DepthAI v3.x)" OFF)
option(BUILD_PLUGIN_OGLO "Build OGLO tactile glove plugin (BLE, Linux only; fetches SimpleBLE + nlohmann/json)" OFF)
option(BUILD_EXAMPLES "Build examples" ON)
option(BUILD_EXAMPLE_TELEOP_ROS2 "Build only the teleop_ros2 example (e.g. for Docker)" OFF)
option(BUILD_TESTING "Build unit tests" ON)
# Televiz (src/viz) needs Vulkan, the CUDA Toolkit, and glslangValidator.
# Default BUILD_VIZ ON when all three are present (so it builds out of the box)
# and OFF otherwise (so a core-only source build still configures on machines
# without them). Override explicitly with -DBUILD_VIZ=ON/OFF.
find_package(Vulkan QUIET)
find_package(CUDAToolkit QUIET)
find_program(_viz_glslang NAMES glslangValidator)
if(Vulkan_FOUND AND CUDAToolkit_FOUND AND _viz_glslang)
    set(_viz_default ON)
else()
    set(_viz_default OFF)
endif()
option(BUILD_VIZ "Build Televiz visualization module (auto-ON when Vulkan + CUDA + glslang are found)" ${_viz_default})
if(BUILD_VIZ AND NOT (Vulkan_FOUND AND CUDAToolkit_FOUND AND _viz_glslang))
    message(WARNING "BUILD_VIZ=ON but not all of Vulkan / CUDA Toolkit / glslangValidator were detected; "
                    "the viz build may fail. Install the deps or pass -DBUILD_VIZ=OFF.")
endif()
message(STATUS "BUILD_VIZ: ${BUILD_VIZ} (Vulkan=${Vulkan_FOUND} CUDAToolkit=${CUDAToolkit_FOUND} glslang=${_viz_glslang})")
option(ENABLE_EXPERIMENTAL_WINDOWS_BUILD "Enable experimental Windows build support (source code only)" OFF)

# Note: This is used to check if the CloudXR bundle is available to be bundled with Isaac Teleop.
# When enabled, build will fail if the CloudXR runtime SDK is not available.
# TODO: Make this default to ON for Linux builds when the CloudXR runtime SDK is publicly available.
option(ENABLE_CLOUDXR_BUNDLE_CHECK "Enable CloudXR bundle check" OFF)

# When ON, also package CloudXR Experimental Runtime SDK as isaacteleop.cloudxr_exp.
option(ENABLE_CLOUDXR_EXP_BUNDLE "Also package CloudXR Experimental Runtime SDK as isaacteleop.cloudxr_exp" OFF)

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

# Build retargeters (pure Python, sibling of src/core)
add_subdirectory(src/retargeters)

# Build haptic device adapters (pure Python, sibling of src/core).
# Vendor-specific pybind extensions (e.g. src/plugins/manus/python) write
# their .so files into the wheel-staging tree at
# python_package/<cfg>/isaacteleop/haptic_devices/ alongside the Python adapter
# modules so adapters can lazy-import them via `from . import _<vendor>_haptic`.
# (cmake-install of those extensions goes to ${CMAKE_INSTALL_LIBDIR} per the
# vendor plugin's own install rules; verify wheel layout matches.)
add_subdirectory(src/haptic_devices)

# Build Televiz visualization module (sibling of src/core).
# src/viz/CMakeLists.txt orchestrates its own sub-modules and tests.
if(BUILD_VIZ)
    add_subdirectory(src/viz)
endif()

# Build examples if requested
if(BUILD_EXAMPLES)
    add_subdirectory(examples/oxr)
    add_subdirectory(examples/retargeting)
    add_subdirectory(examples/teleop_session_manager)
    add_subdirectory(examples/teleop_ros2)
    add_subdirectory(examples/schemaio)
    add_subdirectory(examples/native_openxr)
    add_subdirectory(examples/mcap_record_replay)
    add_subdirectory(examples/deviceio_live_view)
    add_subdirectory(examples/haptic_feedback)
    if(BUILD_VIZ)
        add_subdirectory(examples/camera_viz/tests)
    endif()
elseif(BUILD_EXAMPLE_TELEOP_ROS2)
    add_subdirectory(examples/teleop_ros2)
endif()

# Build plugins if requested
if(BUILD_PLUGINS)
    # Build plugin utilities
    add_subdirectory(src/plugins/plugin_utils)

    add_subdirectory(src/plugins/controller_se3_tracker)
    add_subdirectory(src/plugins/controller_synthetic_hands)
    add_subdirectory(src/plugins/generic_3axis_pedal)
    add_subdirectory(src/plugins/so101_leader)
    add_subdirectory(src/plugins/rebot_devarm_leader)
    add_subdirectory(src/plugins/manus)
    add_subdirectory(src/plugins/haptikos)
    if(BUILD_PLUGIN_OAK_CAMERA)
        add_subdirectory(src/plugins/oak)
    endif()
    if(BUILD_PLUGIN_OGLO)
        add_subdirectory(src/plugins/oglo_tactile)
    endif()
endif()

# Formatting enforcement (runs on Linux by default)
include(cmake/ClangFormat.cmake)
