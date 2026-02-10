# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

pybind11_add_module(schema_py
    oak_bindings.h
    controller_bindings.h
    full_body_bindings.h
    hand_bindings.h
    head_bindings.h
    locomotion_bindings.h
    pedals_bindings.h
    pose_bindings.h
    schema_module.cpp
    tensor_bindings.h
)

target_link_libraries(schema_py
    PRIVATE
        isaacteleop_schema
)

# Ensure generated headers are available.
add_dependencies(schema_py schema_header_generation)

set_target_properties(schema_py PROPERTIES
    OUTPUT_NAME "_schema"
    # Use genex in output directory - CMake won't add another config subdirectory
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/schema"
)
