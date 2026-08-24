# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(schema_tests
  test_oak.cpp
  test_pose.cpp
  test_head.cpp
  test_hand.cpp
  test_full_body.cpp
  test_controller.cpp
  test_pedals.cpp
  test_se3_tracker.cpp
  test_serialized.cpp
  test_schema_conform.cpp
)
target_link_libraries(schema_tests PRIVATE
  isaacteleop_schema
  # check_schema_compat(), shared with the replay read path so both grade a schema
  # change the same way.
  mcap::mcap_core
  Catch2::Catch2WithMain
  OpenXR::headers
)

# test_schema_conform.cpp reads these directories at run time.
add_dependencies(schema_tests schema_binary_schemas)
target_compile_definitions(schema_tests PRIVATE
  SCHEMA_FBS_DIR="${SCHEMA_FBS_DIR}"
  SCHEMA_BFBS_DIR="${SCHEMA_BFBS_DIR}"
  SCHEMA_GOLDEN_DIR="${SCHEMA_GOLDEN_DIR}"
)

message(STATUS "schema_tests target enabled with Catch2")
catch_discover_tests(schema_tests)
