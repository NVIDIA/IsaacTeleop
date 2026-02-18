# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# ==============================================================================
# Clock Sync - types (header-only) + client library + executables + Python
# ==============================================================================

# Header-only library for shared types (clock_types.hpp, platform.hpp)
add_library(clock_sync_types INTERFACE)

target_include_directories(clock_sync_types
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<INSTALL_INTERFACE:include>
)

# On Windows, link Winsock2 and the high-resolution timer API
if(WIN32)
    target_link_libraries(clock_sync_types INTERFACE ws2_32 winmm)
endif()

add_library(utilities::clock_sync_types ALIAS clock_sync_types)

# Static library for the ClockClient class
add_library(clock_sync_client STATIC
    clock_client_lib.cpp
)

target_link_libraries(clock_sync_client
    PUBLIC
        utilities::clock_sync_types
)

target_include_directories(clock_sync_client
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<INSTALL_INTERFACE:include>
)

add_library(utilities::clock_sync_client ALIAS clock_sync_client)

# Clock server executable
add_executable(clock_server clock_server.cpp)
target_link_libraries(clock_server PRIVATE utilities::clock_sync_types)

# Clock client executable (monotonic timestamps, no XR)
add_executable(clock_client clock_client.cpp)
target_link_libraries(clock_client PRIVATE utilities::clock_sync_client)

# ------------------------------------------------------------------------------
# Optional: XR time translator library + XR client executable
# Requires oxr::oxr_core (OpenXR session management + time conversion utilities)
# ------------------------------------------------------------------------------

set(CLOCK_SYNC_HAS_XR OFF)

if(TARGET oxr_core)
    add_library(clock_sync_xr STATIC
        xr_clock_translator.cpp
    )

    target_link_libraries(clock_sync_xr
        PUBLIC
            utilities::clock_sync_types
            oxr::oxr_core
    )

    target_include_directories(clock_sync_xr
        PUBLIC
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
            $<INSTALL_INTERFACE:include>
    )

    add_library(utilities::clock_sync_xr ALIAS clock_sync_xr)

    add_executable(clock_client_xr clock_client_xr.cpp)
    target_link_libraries(clock_client_xr
        PRIVATE
            utilities::clock_sync_client
            utilities::clock_sync_xr
    )

    set(CLOCK_SYNC_HAS_XR ON)
endif()

# Install
set(_CLOCK_SYNC_INSTALL_TARGETS clock_server clock_client clock_sync_client)
if(CLOCK_SYNC_HAS_XR)
    list(APPEND _CLOCK_SYNC_INSTALL_TARGETS clock_client_xr clock_sync_xr)
endif()

install(TARGETS ${_CLOCK_SYNC_INSTALL_TARGETS}
    RUNTIME DESTINATION bin
    ARCHIVE DESTINATION lib
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/clock_sync
    DESTINATION include
)
