# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Static library for plugin utilities
add_library(teleop_plugin_utils STATIC
    hand_injector.cpp
    inc/plugin_utils/hand_injector.hpp
    wrist_pose_source.cpp
    inc/plugin_utils/wrist_pose_source.hpp
)

# Dependencies
# deviceio_session/deviceio_trackers are PUBLIC: wrist_pose_source.hpp exposes
# DeviceIOSession, ITracker and ControllerTracker in its interface.
target_link_libraries(teleop_plugin_utils
    PUBLIC
    deviceio::deviceio_session
    deviceio::deviceio_trackers
    oxr::oxr_utils
    Teleop::openxr_extensions
    OpenXR::openxr_loader
)

# Include directories
target_include_directories(teleop_plugin_utils
    INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# Alias
add_library(Teleop::plugin_utils ALIAS teleop_plugin_utils)
