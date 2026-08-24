# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# mcap_core provides McapTrackerChannels / McapTrackerViewers
# (mcap/tracker_channels.hpp), thin helpers that reduce boilerplate in the
# Live*TrackerImpl and Replay*TrackerImpl constructors and update() methods.
# schema_compat.cpp is the one compiled source: <flatbuffers/idl.h> is heavy and
# is needed only to compare binary schemas, so it stays out of the headers every
# tracker includes.
# The actual MCAP implementation (MCAP_IMPLEMENTATION) is compiled once inside
# deviceio_core (deviceio_session.cpp).
add_library(mcap_core STATIC
    schema_compat.cpp
    inc/mcap/recording_traits.hpp
    inc/mcap/schema_compat.hpp
    inc/mcap/tracker_channels.hpp
)

target_include_directories(mcap_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<BUILD_INTERFACE:${GENERATED_TRACKER_INC_DIR}>
)

# Transitively expose mcap::mcap so consumers get <mcap/writer.hpp>
target_link_libraries(mcap_core
    PUBLIC
        mcap::mcap
        isaacteleop_schema
)

add_library(mcap::mcap_core ALIAS mcap_core)
