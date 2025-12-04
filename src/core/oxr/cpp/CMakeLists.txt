# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# If this is being built standalone, declare a project
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(oxr_core VERSION 1.0.0 LANGUAGES CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

# Ensure OpenXR target is available (fetched via CMake FetchContent by parent)
if(NOT TARGET openxr_loader)
    message(FATAL_ERROR "openxr_loader target not found. Make sure OpenXR SDK is fetched via FetchContent first.")
endif()

# Create OpenXR::OpenXR alias for consistency
if(NOT TARGET OpenXR::OpenXR)
    add_library(OpenXR::OpenXR ALIAS openxr_loader)
endif()

# Core OXR session library (static for distribution)
add_library(oxr_core STATIC
    oxr_session.cpp
    inc/oxr/oxr_session.hpp
)

target_include_directories(oxr_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(oxr_core
    PUBLIC
        OpenXR::OpenXR
        oxr::oxr_utils
)

# Create alias for consistent naming
add_library(oxr::oxr_core ALIAS oxr_core)

# Optional: Install for distribution
install(TARGETS oxr_core
    ARCHIVE DESTINATION lib
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/oxr
    DESTINATION include
)
