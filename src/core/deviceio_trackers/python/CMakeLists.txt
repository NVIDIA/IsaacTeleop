# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

pybind11_add_module(deviceio_trackers_py
    tracker_bindings.cpp
)

target_link_libraries(deviceio_trackers_py
    PRIVATE
        deviceio::deviceio_trackers
)

set_target_properties(deviceio_trackers_py PROPERTIES
    OUTPUT_NAME "_deviceio_trackers"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/deviceio_trackers"
)
