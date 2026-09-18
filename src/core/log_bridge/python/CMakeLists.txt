# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

pybind11_add_module(log_bridge_py
    python_bridge_sink.cpp
    python_bindings.cpp
)

target_link_libraries(log_bridge_py PRIVATE log_bridge::log_bridge_core)

set_target_properties(log_bridge_py PROPERTIES
    OUTPUT_NAME "_log_bridge"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/log_bridge"
)
