# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

if(NOT TARGET openxr_loader)
    message(FATAL_ERROR "viz_xr: openxr_loader target missing (project FetchContent).")
endif()

add_library(viz_xr STATIC
    xr_runtime.cpp
    inc/viz/xr/xr_runtime.hpp
)

target_include_directories(viz_xr PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/inc
)

target_link_libraries(viz_xr PUBLIC
    viz::core
    openxr_loader
)

add_library(viz::xr ALIAS viz_xr)
