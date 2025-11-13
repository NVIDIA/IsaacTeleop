# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Python bindings using pybind11
# Use centralized Python version configuration from root CMakeLists.txt
include(${CMAKE_SOURCE_DIR}/cmake/SetupPython.cmake)

# Additional pybind11 compatibility variables
set(PYTHON_EXECUTABLE "${Python3_EXECUTABLE}" CACHE FILEPATH "Python executable for pybind11" FORCE)
set(PYTHON_INCLUDE_DIRS "${Python3_INCLUDE_DIRS}" CACHE PATH "Python include dirs for pybind11" FORCE)
set(PYTHON_LIBRARIES "${Python3_LIBRARIES}" CACHE FILEPATH "Python libraries for pybind11" FORCE)

# Try to find pybind11 installed on system
find_package(pybind11 CONFIG QUIET)

if(NOT pybind11_FOUND)
    # Use pybind11 from git submodule
    set(PYBIND11_DIR "${CMAKE_SOURCE_DIR}/deps/third_party/pybind11")
    
    if(NOT EXISTS "${PYBIND11_DIR}/CMakeLists.txt")
        message(FATAL_ERROR 
            "pybind11 submodule not found. Please initialize it with:\n"
            "  git submodule update --init --recursive")
    endif()
    
    add_subdirectory("${PYBIND11_DIR}" "${CMAKE_BINARY_DIR}/pybind11_xrio")
    message(STATUS "Using pybind11 from submodule: ${PYBIND11_DIR}")
endif()

# XRIO module (trackers and teleop session)
pybind11_add_module(xrio_py
    xrio_bindings.cpp
)

target_link_libraries(xrio_py
    PRIVATE
        xrio_core
)

set_target_properties(xrio_py PROPERTIES
    OUTPUT_NAME "_xrio"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/teleopcore/xrio"
)

