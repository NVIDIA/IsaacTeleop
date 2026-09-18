# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(log_bridge_tests
  test_logger.cpp
)
target_link_libraries(log_bridge_tests PRIVATE
  log_bridge::log_bridge_core
  Catch2::Catch2WithMain
)

message(STATUS "log_bridge_tests target enabled with Catch2")
catch_discover_tests(log_bridge_tests)
