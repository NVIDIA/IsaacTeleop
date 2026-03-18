# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_library(live_trackers STATIC
    schema_tracker_base.cpp
    live_deviceio_factory.cpp
    live_head_tracker_impl.cpp
    live_hand_tracker_impl.cpp
    live_controller_tracker_impl.cpp
    live_full_body_tracker_pico_impl.cpp
    live_generic_3axis_pedal_tracker_impl.cpp
    live_frame_metadata_tracker_oak_impl.cpp
    inc/live_trackers/schema_tracker_base.hpp
    inc/live_trackers/schema_tracker.hpp
    inc/live_trackers/live_deviceio_factory.hpp
    live_head_tracker_impl.hpp
    live_hand_tracker_impl.hpp
    live_controller_tracker_impl.hpp
    live_full_body_tracker_pico_impl.hpp
    live_generic_3axis_pedal_tracker_impl.hpp
    live_frame_metadata_tracker_oak_impl.hpp
)

target_include_directories(live_trackers
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(live_trackers
    PUBLIC
        deviceio::deviceio_base
        deviceio::deviceio_trackers
        mcap::mcap_core
        Teleop::openxr_extensions
)

add_library(deviceio::live_trackers ALIAS live_trackers)
