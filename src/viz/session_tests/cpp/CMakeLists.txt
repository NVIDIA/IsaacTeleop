# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(viz_session_tests
    test_offscreen_render.cpp
    test_viz_session.cpp
)

target_link_libraries(viz_session_tests PRIVATE
    viz::session
    viz::layers_testing
    Catch2::Catch2WithMain
)

message(STATUS "viz_session_tests target enabled with Catch2")

catch_discover_tests(viz_session_tests ADD_TAGS_AS_LABELS)
