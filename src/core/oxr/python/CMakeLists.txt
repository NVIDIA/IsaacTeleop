# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Python bindings using pybind11
# Use centralized Python version configuration from root CMakeLists.txt
include(${CMAKE_SOURCE_DIR}/cmake/SetupPython.cmake)

# Additional pybind11 compatibility variables (for legacy pybind11 versions)
set(PYTHON_EXECUTABLE "${Python3_EXECUTABLE}" CACHE FILEPATH "Python executable for pybind11" FORCE)
set(PYTHON_INCLUDE_DIRS "${Python3_INCLUDE_DIRS}" CACHE PATH "Python include dirs for pybind11" FORCE)
set(PYTHON_LIBRARIES "${Python3_LIBRARIES}" CACHE FILEPATH "Python libraries for pybind11" FORCE)

# pybind11 should already be available from deps/third_party
if(NOT TARGET pybind11::module)
    message(FATAL_ERROR "pybind11::module target not found. This should be provided by deps/third_party/CMakeLists.txt")
endif()

# OXR module (OpenXR session)
pybind11_add_module(oxr_py
    oxr_bindings.cpp
)

target_link_libraries(oxr_py
    PRIVATE
        oxr_core
)

set_target_properties(oxr_py PROPERTIES
    OUTPUT_NAME "_oxr"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/teleopcore/oxr"
)

