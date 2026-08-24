# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(viz_shaders_tests
    test_shader_blobs.cpp
)

target_link_libraries(viz_shaders_tests PRIVATE
    viz::shaders
    Catch2::Catch2WithMain
)

message(STATUS "viz_shaders_tests target enabled with Catch2")

catch_discover_tests(viz_shaders_tests ADD_TAGS_AS_LABELS)
