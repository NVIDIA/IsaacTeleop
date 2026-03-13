# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Public tracker classes (HeadTracker, HandTracker, etc.)
add_library(deviceio_trackers STATIC
    hand_tracker.cpp
    head_tracker.cpp
    controller_tracker.cpp
    generic_3axis_pedal_tracker.cpp
    frame_metadata_tracker_oak.cpp
    full_body_tracker_pico.cpp
    inc/deviceio_trackers/head_tracker.hpp
    inc/deviceio_trackers/hand_tracker.hpp
    inc/deviceio_trackers/controller_tracker.hpp
    inc/deviceio_trackers/full_body_tracker_pico.hpp
    inc/deviceio_trackers/generic_3axis_pedal_tracker.hpp
    inc/deviceio_trackers/frame_metadata_tracker_oak.hpp
)

target_include_directories(deviceio_trackers
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(deviceio_trackers
    PUBLIC
        deviceio::deviceio_base
)

add_library(deviceio::deviceio_trackers ALIAS deviceio_trackers)
