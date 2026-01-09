# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

pybind11_add_module(deviceio_py
    deviceio_bindings.cpp
)

target_link_libraries(deviceio_py
    PRIVATE
        deviceio_core
)

# Include directory for py_deviceio headers (session.hpp wrapper)
target_include_directories(deviceio_py
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/inc
)

set_target_properties(deviceio_py PROPERTIES
    OUTPUT_NAME "_deviceio"
    # Use genex in output directory - CMake won't add another config subdirectory
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/deviceio"
)
