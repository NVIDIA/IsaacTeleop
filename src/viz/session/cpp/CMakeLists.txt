# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# VizSession + VizCompositor + frame info: orchestration layer that drives
# the per-frame loop and manages the layer registry.
add_library(viz_session STATIC
    viz_compositor.cpp
    viz_session.cpp
    inc/viz/session/frame_info.hpp
    inc/viz/session/viz_compositor.hpp
    inc/viz/session/viz_session.hpp
)

target_include_directories(viz_session
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(viz_session
    PUBLIC
        viz::core
        viz::layers
)

# Aliased as viz::session.
add_library(viz::session ALIAS viz_session)
