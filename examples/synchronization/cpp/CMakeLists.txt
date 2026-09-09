# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(synchronization_example synchronization_example.cpp)
target_link_libraries(synchronization_example PRIVATE synchronization::synchronization)

install(TARGETS synchronization_example
    RUNTIME DESTINATION examples/synchronization/cpp
)
