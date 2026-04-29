# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# LayerBase abstract interface and (later) concrete layer types
# (QuadLayer, ProjectionLayer, OverlayLayer). Header-only today — promoted
# to STATIC when the first .cpp lands. Test-only helper layers
# (e.g. ColoredQuadLayer) live in viz/layers_tests/, not here.
add_library(viz_layers INTERFACE)

target_sources(viz_layers
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc/viz/layers/layer_base.hpp>
)

target_include_directories(viz_layers
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(viz_layers
    INTERFACE
        viz::core
)

# Aliased as viz::layers.
add_library(viz::layers ALIAS viz_layers)
