# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(mcap_tests
  test_mcap_recorder.cpp
)

target_link_libraries(mcap_tests PRIVATE
  mcap_core
  mcap::mcap
  Catch2::Catch2WithMain
)

message(STATUS "mcap_tests target enabled with Catch2")
catch_discover_tests(mcap_tests)


