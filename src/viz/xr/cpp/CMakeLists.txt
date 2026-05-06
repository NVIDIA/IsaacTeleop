# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

if(NOT TARGET openxr_loader)
    message(FATAL_ERROR "viz_xr: openxr_loader target missing (project FetchContent).")
endif()

find_package(Vulkan REQUIRED)

add_library(viz_xr STATIC
    openxr_instance.cpp
    openxr_session.cpp
    xr_runtime.cpp
    inc/viz/xr/openxr_instance.hpp
    inc/viz/xr/openxr_session.hpp
    inc/viz/xr/xr_runtime.hpp
)

target_include_directories(viz_xr PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/inc
)

target_link_libraries(viz_xr PUBLIC
    viz::core
    openxr_loader
    Vulkan::Vulkan
)

add_library(viz::xr ALIAS viz_xr)
