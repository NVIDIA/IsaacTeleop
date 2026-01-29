# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# C++ session sharing example
add_executable(oxr_session_sharing
    oxr_session_sharing.cpp
)

target_link_libraries(oxr_session_sharing
    PRIVATE
        deviceio::deviceio_core
        oxr::oxr_core
)

# Simple API demo example
add_executable(oxr_simple_api_demo
    oxr_simple_api_demo.cpp
)

target_link_libraries(oxr_simple_api_demo
    PRIVATE
        deviceio::deviceio_core
        oxr::oxr_core
)

# Install
install(TARGETS oxr_session_sharing oxr_simple_api_demo
    RUNTIME DESTINATION examples/oxr/cpp
)
