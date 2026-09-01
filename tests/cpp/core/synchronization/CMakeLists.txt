# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

find_package(Threads REQUIRED)

add_executable(synchronization_tests
    test_device_clock_estimator.cpp
)

target_link_libraries(synchronization_tests PRIVATE
    synchronization::synchronization
    Catch2::Catch2WithMain
    Threads::Threads
)

message(STATUS "synchronization_tests target enabled with Catch2")
catch_discover_tests(synchronization_tests)
