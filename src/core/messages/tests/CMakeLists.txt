# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(test_messages
  test_tensor.cpp
  test_pose.cpp
)
target_include_directories(test_messages PRIVATE
  ${CMAKE_SOURCE_DIR}/src
)
target_link_libraries(test_messages PRIVATE
  teleopcore::messages
  Catch2::Catch2WithMain
)

message(STATUS "test_messages target enabled with Catch2")
catch_discover_tests(test_messages)