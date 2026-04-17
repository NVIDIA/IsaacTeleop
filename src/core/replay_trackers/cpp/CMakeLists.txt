# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_library(replay_trackers STATIC
    replay_deviceio_factory.cpp
    replay_hand_tracker_impl.cpp
    replay_head_tracker_impl.cpp
    replay_controller_tracker_impl.cpp
    replay_full_body_tracker_pico_impl.cpp
    replay_generic_3axis_pedal_tracker_impl.cpp
    inc/replay_trackers/replay_deviceio_factory.hpp
    replay_hand_tracker_impl.hpp
    replay_head_tracker_impl.hpp
    replay_controller_tracker_impl.hpp
    replay_full_body_tracker_pico_impl.hpp
    replay_generic_3axis_pedal_tracker_impl.hpp
)

target_include_directories(replay_trackers
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(replay_trackers
    PUBLIC
        deviceio::deviceio_base
        deviceio::deviceio_trackers
        mcap::mcap_core
)

add_library(deviceio::replay_trackers ALIAS replay_trackers)
