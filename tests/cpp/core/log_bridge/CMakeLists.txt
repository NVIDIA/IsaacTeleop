# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# One record, one process, one exit. Every routing case needs its own process
# (see the file header), so both this directory's Catch2 cases and the Python
# logging_config suite run this binary rather than emitting in-process.
add_executable(log_bridge_emit_record
  emit_record.cpp
)
target_link_libraries(log_bridge_emit_record PRIVATE
  log_bridge::log_bridge_core
)

add_executable(log_bridge_tests
  test_logger.cpp
  test_routing.cpp
)
target_link_libraries(log_bridge_tests PRIVATE
  log_bridge::log_bridge_core
  Catch2::Catch2WithMain
)
# test_routing.cpp finds the emitter beside its own executable, so it has to
# exist by the time these tests run -- not merely somewhere in the `all` target.
add_dependencies(log_bridge_tests log_bridge_emit_record)

message(STATUS "log_bridge_tests target enabled with Catch2")
catch_discover_tests(log_bridge_tests)
