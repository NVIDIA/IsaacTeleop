# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Test-only fixture library: concrete LayerBase subclasses that downstream
# tests (here, viz/session_tests/) compose into VizSession to verify
# compositor behavior. Not shipped to consumers.
add_library(viz_layers_testing STATIC
    clear_rect_layer.cpp
    inc/viz/layers/testing/clear_rect_layer.hpp
)

target_include_directories(viz_layers_testing
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(viz_layers_testing
    PUBLIC
        viz::core
        viz::layers
)

add_library(viz::layers_testing ALIAS viz_layers_testing)

# Test executable for the layers_testing fixtures themselves.
add_executable(viz_layers_tests
    test_clear_rect_layer.cpp
)

target_link_libraries(viz_layers_tests PRIVATE
    viz::layers_testing
    Catch2::Catch2WithMain
)

message(STATUS "viz_layers_tests target enabled with Catch2")

catch_discover_tests(viz_layers_tests ADD_TAGS_AS_LABELS)
