# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Abstract APIs and typed tracker impl bases.
add_library(deviceio_base INTERFACE)

target_include_directories(deviceio_base
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(deviceio_base
    INTERFACE
        isaacteleop_schema
        oxr::oxr_utils
        OpenXR::headers
)

add_library(deviceio::deviceio_base ALIAS deviceio_base)
