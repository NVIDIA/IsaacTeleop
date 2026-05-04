# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# LayerBase abstract interface and concrete layer types. Promoted to
# STATIC now that QuadLayer ships. Test-only helper layers
# (ClearRectLayer, ThrowingLayer) live in viz/layers_tests/, not here.
add_library(viz_layers STATIC
    quad_layer.cpp
    inc/viz/layers/layer_base.hpp
    inc/viz/layers/quad_layer.hpp
)

target_include_directories(viz_layers
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(viz_layers
    PUBLIC
        viz::core
    PRIVATE
        viz::shaders
)

# Aliased as viz::layers.
add_library(viz::layers ALIAS viz_layers)
