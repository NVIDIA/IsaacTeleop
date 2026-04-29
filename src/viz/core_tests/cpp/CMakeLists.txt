# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(viz_core_tests
    test_frame_sync.cpp
    test_main.cpp
    test_render_target.cpp
    test_viz_buffer.cpp
    test_viz_types.cpp
    test_vk_context.cpp
    test_helpers.hpp
)

# We use Catch2 (not Catch2WithMain) and provide our own main() in
# test_main.cpp to explicitly tear down the shared VkContext before
# static destruction order can race the Vulkan loader.
target_link_libraries(viz_core_tests PRIVATE
    viz::core
    Catch2::Catch2
)

message(STATUS "viz_core_tests target enabled with Catch2")

# ADD_TAGS_AS_LABELS lets CTest filter by Catch2 tags via -L (e.g. -L unit, -L gpu).
catch_discover_tests(viz_core_tests ADD_TAGS_AS_LABELS)
