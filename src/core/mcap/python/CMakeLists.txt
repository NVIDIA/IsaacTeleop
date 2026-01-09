# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Python bindings using pybind11
# Use centralized Python version configuration from root CMakeLists.txt

# Additional pybind11 compatibility variables (for legacy pybind11 versions)
set(PYTHON_EXECUTABLE "${Python3_EXECUTABLE}" CACHE FILEPATH "Python executable for pybind11" FORCE)
set(PYTHON_INCLUDE_DIRS "${Python3_INCLUDE_DIRS}" CACHE PATH "Python include dirs for pybind11" FORCE)
set(PYTHON_LIBRARIES "${Python3_LIBRARIES}" CACHE FILEPATH "Python libraries for pybind11" FORCE)

# pybind11 should already be available from deps/third_party
if(NOT TARGET pybind11::module)
    message(FATAL_ERROR "pybind11::module target not found. This should be provided by deps/third_party/CMakeLists.txt")
endif()

# MCAP module (McapRecorder)
pybind11_add_module(mcap_py
    mcap_bindings.cpp
)

target_link_libraries(mcap_py
    PRIVATE
        mcap::mcap_core
        deviceio::deviceio_core
)

# Include deviceio python headers for PyDeviceIOSession wrapper
target_include_directories(mcap_py
    PRIVATE
        ${CMAKE_SOURCE_DIR}/src/core/deviceio/python/inc
)

set_target_properties(mcap_py PROPERTIES
    OUTPUT_NAME "_mcap"
    # Use genex in output directory - CMake won't add another config subdirectory
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/mcap"
)
