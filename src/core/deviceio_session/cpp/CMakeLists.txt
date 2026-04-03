# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# DeviceIOSession — wires trackers to the live factory and runs the update loop.
add_library(deviceio_session STATIC
    deviceio_session.cpp
    inc/deviceio_session/deviceio_session.hpp
)

target_include_directories(deviceio_session
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# Public headers include oxr_funcs.hpp and oxr_session_handles.hpp. Propagate
# oxr::oxr_utils (OpenXR headers + oxr inc/) and Teleop::openxr_extensions (NVIDIA
# extension headers) so consumers (Python bindings, apps) compile without linking
# live_trackers.
target_link_libraries(deviceio_session
    PUBLIC
        deviceio::deviceio_base
        oxr::oxr_utils
        Teleop::openxr_extensions
    PRIVATE
        deviceio::deviceio_trackers
        deviceio::live_trackers
        mcap::mcap
)

add_library(deviceio::deviceio_session ALIAS deviceio_session)
