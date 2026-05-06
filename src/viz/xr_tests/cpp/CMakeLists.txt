# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(viz_xr_tests
    test_openxr_instance.cpp
    test_xr_runtime.cpp
)

target_link_libraries(viz_xr_tests PRIVATE
    viz::xr
    Catch2::Catch2WithMain
)

message(STATUS "viz_xr_tests target enabled with Catch2")

catch_discover_tests(viz_xr_tests ADD_TAGS_AS_LABELS)
