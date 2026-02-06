# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Ensure OpenXR headers target is available
if(NOT TARGET OpenXR::headers)
    message(FATAL_ERROR "OpenXR::headers target not found. Make sure OpenXR SDK is configured first.")
endif()

# OXR Utils - Header-only utility library for OpenXR types
# This library provides common OpenXR type definitions without linking to OpenXR loader
add_library(oxr_utils INTERFACE)

target_include_directories(oxr_utils
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<INSTALL_INTERFACE:include>
)

# Link with OpenXR::headers to get OpenXR header files (no loader linking)
target_link_libraries(oxr_utils
    INTERFACE
        OpenXR::headers
)

# Platform-specific definitions for XrTime conversion (used by oxr_time.hpp)
if(WIN32)
    target_compile_definitions(oxr_utils INTERFACE XR_USE_PLATFORM_WIN32 NOMINMAX)
else()
    target_compile_definitions(oxr_utils INTERFACE XR_USE_TIMESPEC)
endif()

# Create alias for consistent naming
add_library(oxr::oxr_utils ALIAS oxr_utils)

# Optional: Install for distribution
install(TARGETS oxr_utils
    EXPORT oxr_utils-targets
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/oxr_utils
    DESTINATION include
)

install(EXPORT oxr_utils-targets
    FILE oxr_utils-targets.cmake
    NAMESPACE oxr::
    DESTINATION lib/cmake/oxr_utils
)

