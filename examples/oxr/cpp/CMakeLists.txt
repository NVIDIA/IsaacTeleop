# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# When building from top-level, targets are already defined
# We need both oxr_core and deviceio_core for the examples
if(NOT TARGET deviceio::deviceio_core)
    find_package(deviceio_core REQUIRED)
    find_package(oxr_core REQUIRED)
endif()

# C++ session sharing example
add_executable(oxr_session_sharing
    oxr_session_sharing.cpp
)

target_link_libraries(oxr_session_sharing
    PRIVATE
        deviceio::deviceio_core
        oxr::oxr_core
)

# Set C++ standard for this target only
set_target_properties(oxr_session_sharing PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
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

set_target_properties(oxr_simple_api_demo PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)

# Install
install(TARGETS oxr_session_sharing oxr_simple_api_demo
    RUNTIME DESTINATION examples/oxr/cpp
)
