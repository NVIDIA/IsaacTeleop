# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

find_package(Threads REQUIRED)

# Create pusher executable
add_executable(hello_tensor_pusher
    hello_tensor_pusher.cpp
    hello_tensor_plugin.cpp
    hello_tensor_plugin.hpp
)

target_link_libraries(hello_tensor_pusher PRIVATE
    oxr::oxr_core
    oxr::oxr_utils
    OpenXR::openxr_loader
    Teleop::openxr_extensions
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Create reader executable
add_executable(hello_tensor_reader
    hello_tensor_reader.cpp
)

target_link_libraries(hello_tensor_reader PRIVATE
    oxr::oxr_core
    oxr::oxr_utils
    OpenXR::openxr_loader
    Teleop::openxr_extensions
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Install
install(TARGETS hello_tensor_pusher hello_tensor_reader
    RUNTIME DESTINATION examples/hello_tensor
)

install(FILES README.md
    DESTINATION examples/hello_tensor
)
