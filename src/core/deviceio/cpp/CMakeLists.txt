# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# If this is being built standalone, declare a project
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(deviceio_core VERSION 1.0.0 LANGUAGES CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

# DEVICEIO only depends on oxr_utils (header-only library with OpenXR types)
# It does NOT depend on or link to the OpenXR loader
if(NOT TARGET oxr::oxr_utils)
    message(FATAL_ERROR "oxr_utils target not found. Make sure oxr_utils is built first.")
endif()

# Core DEVICEIO tracking library (static for distribution)
add_library(deviceio_core STATIC
    hand_tracker.cpp
    head_tracker.cpp
    controller_tracker.cpp
    deviceio_session.cpp
    inc/deviceio/tracker.hpp
    inc/deviceio/hand_tracker.hpp
    inc/deviceio/head_tracker.hpp
    inc/deviceio/controller_tracker.hpp
    inc/deviceio/deviceio_session.hpp
)

target_include_directories(deviceio_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(deviceio_core
    PUBLIC
        # oxr_utils is header-only and provides OpenXRSessionHandles struct
        # It also brings in OpenXR headers for base types without linking to OpenXR loader
        oxr::oxr_utils

        # Schema library for FlatBuffer types
        teleopcore_schema
)

# Platform-specific definitions
if(WIN32)
    target_compile_definitions(deviceio_core PUBLIC XR_USE_PLATFORM_WIN32 NOMINMAX)
else()
    target_compile_definitions(deviceio_core PUBLIC XR_USE_TIMESPEC)
endif()

# DEVICEIO does NOT link to OpenXR loader - it's completely standalone
# All OpenXR functions are loaded dynamically via xrGetInstanceProcAddr at runtime

# Create alias for consistent naming
add_library(deviceio::deviceio_core ALIAS deviceio_core)

# Optional: Install for distribution
install(TARGETS deviceio_core
    ARCHIVE DESTINATION lib
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/deviceio
    DESTINATION include
)
