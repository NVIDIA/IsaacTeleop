# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

pybind11_add_module(plugin_manager_py
    plugin_manager_bindings.cpp
)

target_link_libraries(plugin_manager_py
    PRIVATE
        teleop_plugin_manager
)

set_target_properties(plugin_manager_py PROPERTIES
    OUTPUT_NAME "_plugin_manager"
    # Use genex in output directory - CMake won't add another config subdirectory
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/plugin_manager"
)
