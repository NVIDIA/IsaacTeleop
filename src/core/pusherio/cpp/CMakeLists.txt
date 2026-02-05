# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# PusherIO library (static for distribution)
add_library(pusherio STATIC
    schema_pusher.cpp
    inc/pusherio/schema_pusher.hpp
)

target_include_directories(pusherio
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(pusherio
    PUBLIC
        # oxr_utils is header-only and provides OpenXRSessionHandles struct
        # It also brings in OpenXR headers for base types without linking to OpenXR loader
        oxr::oxr_utils

        # OpenXR extensions for push tensor and tensor data APIs
        Teleop::openxr_extensions
)

# pusherio does NOT link to OpenXR loader - it's completely standalone
# All OpenXR functions are loaded dynamically via xrGetInstanceProcAddr at runtime

# Create alias for consistent naming
add_library(pusherio::pusherio ALIAS pusherio)

# Optional: Install for distribution
install(TARGETS pusherio
    ARCHIVE DESTINATION lib
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/pusherio
    DESTINATION include
)
