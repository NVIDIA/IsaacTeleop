# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(viz_window_smoke main.cpp)

target_link_libraries(viz_window_smoke PRIVATE
    viz::session
    viz::layers
)

set_target_properties(viz_window_smoke PROPERTIES OUTPUT_NAME "viz_window_smoke")
install(TARGETS viz_window_smoke RUNTIME DESTINATION examples/televiz/window_smoke)
