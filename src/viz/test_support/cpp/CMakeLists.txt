# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Header-only INTERFACE library exposing test_helpers.hpp:
# is_gpu_available(), shared_vk_context(), GpuFixture. Used by all
# viz_*_tests so the probes have one canonical implementation.
add_library(viz_test_support INTERFACE)
target_include_directories(viz_test_support INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
)
target_link_libraries(viz_test_support INTERFACE
    viz::core
    Catch2::Catch2
)
add_library(viz::test_support ALIAS viz_test_support)
