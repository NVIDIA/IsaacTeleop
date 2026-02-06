# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

pybind11_add_module(mcap_py
    mcap_bindings.cpp
)

target_link_libraries(mcap_py
    PRIVATE
        mcap::mcap_core
        deviceio::deviceio_core
        deviceio_py_utils
)

set_target_properties(mcap_py PROPERTIES
    OUTPUT_NAME "_mcap"
    # Use genex in output directory - CMake won't add another config subdirectory
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/mcap"
)
