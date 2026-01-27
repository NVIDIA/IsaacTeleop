# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Skip camera plugins on Windows - requires pkg-config and Unix build tools
if(WIN32)
    message(STATUS "Camera plugins: Skipping on Windows (requires pkg-config and Unix build tools)")
    return()
endif()

include(ExternalProject)
include(GNUInstallDirs)

find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)

# ==============================================================================
# FFmpeg Setup (shared by all camera plugins)
# ==============================================================================
set(FFMPEG_INSTALL_DIR ${CMAKE_BINARY_DIR}/ffmpeg-install)

# Check if FFmpeg is already built locally
if(EXISTS ${FFMPEG_INSTALL_DIR}/lib/pkgconfig/libavformat.pc)
    message(STATUS "Found pre-built FFmpeg at ${FFMPEG_INSTALL_DIR}")
    set(FFMPEG_PREBUILT TRUE)
else()
    # Check for system FFmpeg
    pkg_check_modules(LIBAV_SYSTEM QUIET libavformat libavcodec libavutil)
    if(LIBAV_SYSTEM_FOUND)
        message(STATUS "Found system FFmpeg: ${LIBAV_SYSTEM_VERSION}")
        set(FFMPEG_USE_SYSTEM TRUE)
    else()
        message(STATUS "FFmpeg not found - will be built as external project")
        message(STATUS "  First build takes ~5-10 minutes, subsequent builds are fast")
        set(FFMPEG_PREBUILT FALSE)
        set(FFMPEG_USE_SYSTEM FALSE)
    endif()
endif()

# Build FFmpeg from source if not available
if(NOT FFMPEG_PREBUILT AND NOT FFMPEG_USE_SYSTEM)
    ExternalProject_Add(ffmpeg_external
        URL https://ffmpeg.org/releases/ffmpeg-6.1.tar.xz
        URL_HASH SHA256=488c76e57dd9b3bee901f71d5c95eaf1db4a5a31fe46a28654e837144207c270
        CONFIGURE_COMMAND <SOURCE_DIR>/configure
            --prefix=${FFMPEG_INSTALL_DIR}
            --disable-programs
            --disable-doc
            --disable-network
            --disable-x86asm
            --disable-everything
            --enable-muxer=mp4
            --enable-protocol=file
            --enable-static
            --disable-shared
            --enable-pic
        BUILD_COMMAND make -j${CMAKE_BUILD_PARALLEL_LEVEL}
        INSTALL_COMMAND make install
        BUILD_IN_SOURCE 0
    )
    set(FFMPEG_READY FALSE)
else()
    set(FFMPEG_READY TRUE)
endif()

# Setup FFmpeg for use by subdirectories
if(FFMPEG_READY)
    if(FFMPEG_PREBUILT)
        set(ENV{PKG_CONFIG_PATH} "${FFMPEG_INSTALL_DIR}/lib/pkgconfig:$ENV{PKG_CONFIG_PATH}")
        set(CMAKE_PREFIX_PATH ${FFMPEG_INSTALL_DIR} ${CMAKE_PREFIX_PATH})
    endif()
    
    pkg_check_modules(LIBAV REQUIRED IMPORTED_TARGET libavformat libavcodec libavutil)
    message(STATUS "Using FFmpeg: ${LIBAV_VERSION}")
endif()

# ==============================================================================
# Shared headers location
# ==============================================================================
set(CAMERA_PLUGIN_INC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/inc")

# ==============================================================================
# Build shared core library (requires FFmpeg)
# ==============================================================================
if(FFMPEG_READY)
    message(STATUS "Building camera plugin core library")
    add_subdirectory(core)
    add_library(isaac::camera_plugin ALIAS camera_plugin_core)
    
    # Build camera plugin implementations
    add_subdirectory(oakd)
else()
    message(STATUS "Camera plugin core: FFmpeg not ready")
    message(STATUS "  Run: cmake --build build --target ffmpeg_external")
    message(STATUS "  Then: cmake -B build")
endif()
