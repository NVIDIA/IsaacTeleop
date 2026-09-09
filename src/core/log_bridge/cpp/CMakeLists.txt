# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Core Logger library (static; consumed in-tree via log_bridge::log_bridge_core).
# No pybind11/Python.h anywhere in this target -- every standalone plugin
# executable and Catch2 test binary links this without pulling in libpython.
add_library(log_bridge_core STATIC
    log_relay.cpp
    logger.cpp
    sink_config.cpp
    sink_config.hpp
    inc/log_bridge/log_relay.hpp
    inc/log_bridge/logger.hpp
)

target_include_directories(log_bridge_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(log_bridge_core
    PUBLIC
        spdlog::spdlog
)

add_library(log_bridge::log_bridge_core ALIAS log_bridge_core)
