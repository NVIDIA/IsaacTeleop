# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Vulkan is required for vk_context.
find_package(Vulkan REQUIRED)

# Foundational types and Vulkan/CUDA primitives shared by all viz sub-modules.
# Static lib; consumed in-tree via viz::viz_core.
add_library(viz_core STATIC
    frame_sync.cpp
    render_target.cpp
    vk_context.cpp
    inc/viz/core/frame_sync.hpp
    inc/viz/core/host_image.hpp
    inc/viz/core/render_target.hpp
    inc/viz/core/viz_buffer.hpp
    inc/viz/core/viz_types.hpp
    inc/viz/core/vk_context.hpp
)

target_include_directories(viz_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(viz_core
    PUBLIC
        Vulkan::Vulkan
        glm::glm
)

# Aliased as viz::core (consumers say viz::core, not viz::viz_core).
add_library(viz::core ALIAS viz_core)
