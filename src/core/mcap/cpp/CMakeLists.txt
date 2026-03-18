# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# mcap_core is a header-only interface library.
# It provides McapTrackerChannels (mcap/tracker_channels.hpp) -- a thin helper
# that reduces boilerplate in Live*TrackerImpl constructors and update() methods.
# The actual MCAP implementation (MCAP_IMPLEMENTATION) is compiled once inside
# deviceio_core (deviceio_session.cpp).
add_library(mcap_core INTERFACE)

target_include_directories(mcap_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# Transitively expose mcap::mcap so consumers get <mcap/writer.hpp>
target_link_libraries(mcap_core
    INTERFACE
        mcap::mcap
        isaacteleop_schema
)

add_library(mcap::mcap_core ALIAS mcap_core)
