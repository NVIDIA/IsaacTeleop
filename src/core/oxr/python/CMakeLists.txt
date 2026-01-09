# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

pybind11_add_module(oxr_py
    oxr_bindings.cpp
)

target_link_libraries(oxr_py
    PRIVATE
        oxr_core
)

set_target_properties(oxr_py PROPERTIES
    OUTPUT_NAME "_oxr"
    # Use genex in output directory - CMake won't add another config subdirectory
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/oxr"
)

