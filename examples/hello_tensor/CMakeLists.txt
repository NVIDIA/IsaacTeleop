# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

find_package(Threads REQUIRED)

# Create pusher executable using tensorio library
add_executable(hello_tensor_pusher
    hello_tensor_pusher.cpp
)

target_link_libraries(hello_tensor_pusher PRIVATE
    oxr::oxr_core
    tensorio::tensorio_core
    OpenXR::openxr_loader
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Create reader executable using tensorio library
add_executable(hello_tensor_reader
    hello_tensor_reader.cpp
)

target_link_libraries(hello_tensor_reader PRIVATE
    oxr::oxr_core
    tensorio::tensorio_core
    OpenXR::openxr_loader
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
