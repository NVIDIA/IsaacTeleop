# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# SetupPython.cmake
# ==============================================================================
# Centralizes Python executable discovery and configuration.
# Uses the ISAAC_TELEOP_PYTHON_VERSION variable from root CMakeLists.txt.
#
# This module uses uv to install and find the managed Python version.
# It ALWAYS uses uv-managed Python, ignoring any venv or system Python.
#
# Usage: include(cmake/SetupPython.cmake)
# ==============================================================================

if(NOT DEFINED ISAAC_TELEOP_PYTHON_VERSION)
    message(FATAL_ERROR "ISAAC_TELEOP_PYTHON_VERSION must be set before including SetupPython.cmake")
endif()

option(BUILD_PYTHON_BINDINGS "Build Python bindings" ON)

# Guard to prevent multiple inclusions from overwriting our settings
if(NOT ISAAC_TELEOP_PYTHON_CONFIGURED)
    # Unset any previously found Python to prevent interference from venvs
    unset(Python3_EXECUTABLE CACHE)
    unset(Python3_LIBRARY CACHE)
    unset(Python3_INCLUDE_DIR CACHE)
    unset(PYTHON_EXECUTABLE CACHE)

    # Check if uv is available
    find_program(UV_EXECUTABLE uv)

    if(NOT UV_EXECUTABLE)
        message(FATAL_ERROR "uv not found. Please install uv: curl -LsSf https://astral.sh/uv/install.sh | sh")
    endif()

    # First, ensure the required Python version is installed as a managed version
    message(STATUS "Ensuring Python ${ISAAC_TELEOP_PYTHON_VERSION} is installed via uv...")
    execute_process(
        COMMAND ${UV_EXECUTABLE} python install ${ISAAC_TELEOP_PYTHON_VERSION} --quiet
        OUTPUT_QUIET
        ERROR_QUIET
        RESULT_VARIABLE UV_INSTALL_RESULT
    )

    # Now find the managed Python
    execute_process(
        COMMAND ${UV_EXECUTABLE} python find ${ISAAC_TELEOP_PYTHON_VERSION}
        OUTPUT_VARIABLE UV_PYTHON_PATH
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
        RESULT_VARIABLE UV_FIND_RESULT
    )

    if(NOT UV_FIND_RESULT EQUAL 0 OR NOT EXISTS "${UV_PYTHON_PATH}")
        message(FATAL_ERROR "Could not find managed Python ${ISAAC_TELEOP_PYTHON_VERSION} with uv.")
    endif()

    # Force CMake to use our specific Python
    set(Python3_EXECUTABLE "${UV_PYTHON_PATH}" CACHE FILEPATH "Path to Python3 executable" FORCE)
    set(PYTHON_EXECUTABLE "${UV_PYTHON_PATH}" CACHE FILEPATH "Path to Python executable" FORCE)
    message(STATUS "Using managed Python ${ISAAC_TELEOP_PYTHON_VERSION} from uv: ${Python3_EXECUTABLE}")

    # Find Python using the executable we determined
    # Use EXACT to prevent CMake from finding a different version
    find_package(Python3 ${ISAAC_TELEOP_PYTHON_VERSION} EXACT REQUIRED COMPONENTS Interpreter Development)

    message(STATUS "Building Python bindings with: ${Python3_EXECUTABLE} (version ${Python3_VERSION})")

    # Force pybind11 to use the same Python version and libraries
    set(PYBIND11_PYTHON_VERSION "${Python3_VERSION}" CACHE STRING "Python version for pybind11" FORCE)
    set(PYBIND11_PYTHON_INCLUDE_DIR "${Python3_INCLUDE_DIRS}" CACHE STRING "Python include dir for pybind11" FORCE)
    set(PYBIND11_PYTHON_LIBRARIES "${Python3_LIBRARIES}" CACHE STRING "Python libraries for pybind11" FORCE)

    # Set legacy variables for compatibility (important for some find modules)
    set(PYTHON_INCLUDE_DIRS "${Python3_INCLUDE_DIRS}" CACHE PATH "Python include dirs" FORCE)
    set(PYTHON_LIBRARIES "${Python3_LIBRARIES}" CACHE FILEPATH "Python libraries" FORCE)

    # Mark as configured to prevent re-running
    set(ISAAC_TELEOP_PYTHON_CONFIGURED TRUE CACHE INTERNAL "Python configuration completed")
endif()

# ==============================================================================
# NumPy 2.x build venv
# ==============================================================================
# When building Python bindings, extensions must be compiled against NumPy 2.x so a single
# wheel works with both NumPy 1.x and 2.x at runtime. The uv-managed Python cannot be
# modified, so we create a build venv with numpy>=2.0 when needed.
if(BUILD_PYTHON_BINDINGS)
    set(_build_venv "${CMAKE_BINARY_DIR}/teleop_build_venv")
    execute_process(
        COMMAND "${Python3_EXECUTABLE}" -c
            "import sys, re; import numpy; p = re.findall(r'\\d+', numpy.__version__); v = (int(p[0]), int(p[1])) if len(p) >= 2 else (int(p[0]), 0) if p else (0, 0); sys.exit(0 if v >= (2, 0) else 1)"
        RESULT_VARIABLE _numpy_ok
        ERROR_QUIET
        OUTPUT_QUIET
    )
    if(NOT _numpy_ok EQUAL 0)
        message(STATUS "Creating build venv with numpy>=2.0 for ABI-compatible extensions...")
        execute_process(
            COMMAND "${UV_EXECUTABLE}" venv --python "${Python3_EXECUTABLE}" "${_build_venv}"
            RESULT_VARIABLE _venv_ok
            ERROR_VARIABLE _venv_err
        )
        if(NOT _venv_ok EQUAL 0)
            message(FATAL_ERROR "Failed to create build venv: ${_venv_err}")
        endif()
        if(CMAKE_SYSTEM_NAME STREQUAL "Windows")
            set(_venv_python "${_build_venv}/Scripts/python.exe")
        else()
            set(_venv_python "${_build_venv}/bin/python")
        endif()
        execute_process(
            COMMAND "${UV_EXECUTABLE}" pip install --python "${_venv_python}" "numpy>=2.0"
            RESULT_VARIABLE _pip_ok
            ERROR_VARIABLE _pip_err
        )
        if(NOT _pip_ok EQUAL 0)
            message(FATAL_ERROR "Failed to install numpy>=2.0 in build venv: ${_pip_err}")
        endif()
        set(Python3_EXECUTABLE "${_venv_python}" CACHE FILEPATH "Path to Python3 executable (build venv)" FORCE)
        set(PYTHON_EXECUTABLE "${_venv_python}" CACHE FILEPATH "Path to Python executable (build venv)" FORCE)
        message(STATUS "Using build venv Python: ${Python3_EXECUTABLE}")
    endif()
endif()
