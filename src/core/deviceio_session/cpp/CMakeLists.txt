# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# DeviceIOSession — shared tracker session logic.
# Live and replay subclasses are private implementation details.
add_library(deviceio_session STATIC
    deviceio_session.cpp
    inc/deviceio_session/deviceio_session.hpp
)

target_include_directories(deviceio_session
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# Public header includes oxr_session_handles.hpp (OpenXR types). Propagate
# oxr::oxr_utils so consumers get OpenXR headers and oxr include paths.
target_link_libraries(deviceio_session
    PUBLIC
        deviceio::deviceio_base
        oxr::oxr_utils
    PRIVATE
        deviceio::deviceio_trackers
        deviceio::live_trackers
        deviceio::replay_trackers
        mcap::mcap
)

add_library(deviceio::deviceio_session ALIAS deviceio_session)
