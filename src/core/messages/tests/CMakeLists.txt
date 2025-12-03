# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(test_tensor test_tensor.cpp)
target_link_libraries(test_tensor PRIVATE
  teleopcore::messages
  Catch2::Catch2WithMain
)

message(STATUS "test_tensor target enabled with Catch2")
catch_discover_tests(test_tensor)