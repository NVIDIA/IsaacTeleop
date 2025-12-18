# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# XRIO only depends on oxr_utils (header-only library with OpenXR types)
# It does NOT depend on or link to the OpenXR loader
if(NOT TARGET oxr::oxr_utils)
    message(FATAL_ERROR "oxr_utils target not found. Make sure oxr_utils is built first.")
endif()

# Core XRIO tracking library (static for distribution)
add_library(xrio_core STATIC
    handtracker.cpp
    headtracker.cpp
    controllertracker.cpp
    xrio_session.cpp
    inc/xrio/tracker.hpp
    inc/xrio/handtracker.hpp
    inc/xrio/headtracker.hpp
    inc/xrio/controllertracker.hpp
    inc/xrio/xrio_session.hpp
)

target_include_directories(xrio_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(xrio_core
    PUBLIC
        # oxr_utils is header-only and provides OpenXRSessionHandles struct
        # It also brings in OpenXR headers for base types without linking to OpenXR loader
        oxr::oxr_utils

        # Schema library for FlatBuffer types
        teleopcore_schema
)

# Platform-specific definitions
if(WIN32)
    target_compile_definitions(xrio_core PUBLIC XR_USE_PLATFORM_WIN32)
else()
    target_compile_definitions(xrio_core PUBLIC XR_USE_TIMESPEC)
endif()

# XRIO does NOT link to OpenXR loader - it's completely standalone
# All OpenXR functions are loaded dynamically via xrGetInstanceProcAddr at runtime

# Create alias for consistent naming
add_library(xrio::xrio_core ALIAS xrio_core)

# Optional: Install for distribution
install(TARGETS xrio_core
    ARCHIVE DESTINATION lib
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/xrio
    DESTINATION include
)

