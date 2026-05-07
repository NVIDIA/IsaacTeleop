# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Concrete layer implementations (QuadLayer, ...). LayerBase — the
# session's contract for what a layer is — lives in viz::session, not
# here, so we depend on viz::session for the base class. Test-only
# helper layers (ClearRectLayer, ThrowingLayer) live in
# viz/layers_tests/.
add_library(viz_layers STATIC
    quad_layer.cpp
    inc/viz/layers/quad_layer.hpp
)

target_include_directories(viz_layers
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(viz_layers
    PUBLIC
        viz::core
        viz::session
    PRIVATE
        viz::shaders
)

# Aliased as viz::layers.
add_library(viz::layers ALIAS viz_layers)
