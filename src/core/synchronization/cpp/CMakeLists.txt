# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

find_package(Threads REQUIRED)

# Synchronization - maps a device's own free-running clock onto the local common clock.
# Pure arithmetic over round-trip observations: no transport, no threads, no device knowledge,
# and therefore no dependencies beyond the standard library.
add_library(synchronization
    device_clock_estimator.cpp
)

target_link_libraries(synchronization PRIVATE Threads::Threads)

target_include_directories(synchronization
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

add_library(synchronization::synchronization ALIAS synchronization)
