# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(schema_tests
  test_oak.cpp
  test_tensor.cpp
  test_pose.cpp
  test_head.cpp
  test_hand.cpp
  test_full_body.cpp
  test_controller.cpp
  test_locomotion.cpp
  test_pedals.cpp
)
target_link_libraries(schema_tests PRIVATE
  isaacteleop_schema
  Catch2::Catch2WithMain
)

message(STATUS "schema_tests target enabled with Catch2")
catch_discover_tests(schema_tests)