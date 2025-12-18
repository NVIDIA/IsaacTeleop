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

# DEVICEIO module (trackers and teleop session)
pybind11_add_module(deviceio_py
    deviceio_bindings.cpp
)

target_link_libraries(deviceio_py
    PRIVATE
        deviceio_core
)

set_target_properties(deviceio_py PROPERTIES
    OUTPUT_NAME "_deviceio"
    # Use genex in output directory - CMake won't add another config subdirectory
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/deviceio"
)

