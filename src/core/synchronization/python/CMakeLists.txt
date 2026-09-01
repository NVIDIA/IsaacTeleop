# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

pybind11_add_module(synchronization_py
    synchronization_bindings.cpp
)

target_link_libraries(synchronization_py
    PRIVATE
        synchronization::synchronization
)

set_target_properties(synchronization_py PROPERTIES
    OUTPUT_NAME "_synchronization"
    # Use genex in output directory - CMake won't add another config subdirectory
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/synchronization"
)
