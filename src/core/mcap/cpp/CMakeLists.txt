# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# MCAP Recorder library (static for distribution)
add_library(mcap_core STATIC
    mcap_recorder.cpp
    inc/mcap_recorder.hpp
)

# Public headers for consumers of this library
target_include_directories(mcap_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# Include deviceio headers for ITrackerImpl interface (header-only dependency)
target_include_directories(mcap_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../deviceio/cpp/inc>
)

# mcap_core needs the same dependencies as deviceio for the tracker interface
# but does NOT link to deviceio_core to avoid circular dependency
target_link_libraries(mcap_core
    PUBLIC
        # oxr_utils for OpenXR types used in tracker.hpp
        oxr::oxr_utils
        # Schema library for FlatBuffer types used in tracker.hpp
        teleopcore_schema
        # MCAP header-only library (PUBLIC because mcap_recorder.hpp includes mcap/types.hpp)
        mcap::mcap
)

# Create alias for consistent naming
add_library(mcap::mcap_core ALIAS mcap_core)

# Optional: Install for distribution
install(TARGETS mcap_core
    ARCHIVE DESTINATION lib
    INCLUDES DESTINATION include
)

install(FILES inc/mcap_recorder.hpp
    DESTINATION include
)

