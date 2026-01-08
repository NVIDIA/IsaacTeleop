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

# mcap_core depends on deviceio_core for DeviceIOSession and tracker interfaces
target_link_libraries(mcap_core
    PUBLIC
        # deviceio_core for DeviceIOSession and ITracker interfaces
        deviceio::deviceio_core
    PRIVATE
        # MCAP header-only library (PRIVATE - implementation detail)
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
