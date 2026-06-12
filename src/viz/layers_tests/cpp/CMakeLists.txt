# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Test executable for the viz::layers_testing fixtures themselves and for
# the production layers in viz::layers (QuadLayer, ...).
add_executable(viz_layers_tests
    test_clear_rect_layer.cpp
    test_quad_layer.cpp
    test_throwing_layer.cpp
)

target_link_libraries(viz_layers_tests PRIVATE
    viz::layers_testing
    viz::layers
    viz::test_support
    Catch2::Catch2WithMain
)

message(STATUS "viz_layers_tests target enabled with Catch2")

catch_discover_tests(viz_layers_tests ADD_TAGS_AS_LABELS)
