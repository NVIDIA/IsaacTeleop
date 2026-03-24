# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Time Utils - Header-only platform clock utilities (no OpenXR dependency)
add_library(time_utils INTERFACE)

target_include_directories(time_utils
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

add_library(core::time_utils ALIAS time_utils)
