cmake_minimum_required(VERSION 3.20)
project(TeleopCore VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
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

# Set default build type to Release if not specified
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Set default install prefix to local install/ directory if not specified
if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT)
    set(CMAKE_INSTALL_PREFIX "${CMAKE_SOURCE_DIR}/install" CACHE PATH "Install prefix" FORCE)
endif()

# Options
option(BUILD_EXAMPLES "Build examples" ON)
option(BUILD_PYTHON_BINDINGS "Build Python bindings" ON)

# Always build OpenXR SDK from submodule
if(NOT EXISTS "${CMAKE_SOURCE_DIR}/deps/third_party/openxr-sdk/CMakeLists.txt")
    message(FATAL_ERROR "OpenXR SDK submodule not found. Please run: git submodule update --init --recursive")
endif()

# Build OpenXR loader as a static library to avoid runtime dependency issues
set(DYNAMIC_LOADER OFF CACHE BOOL "Build OpenXR loader as static library" FORCE)
add_subdirectory(deps/third_party/openxr-sdk)
message(STATUS "Building OpenXR SDK from submodule (static library)")

# Build core modules (OXR and XRIO)
add_subdirectory(src/core)

# Build examples if requested
if(BUILD_EXAMPLES)
    add_subdirectory(examples/oxr)
endif()
