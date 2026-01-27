# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Skip camera plugin on Windows - requires pkg-config and Unix build tools
if(WIN32)
    message(STATUS "Camera plugin: Skipping on Windows (requires pkg-config and Unix build tools)")
    return()
endif()

include(ExternalProject)
include(GNUInstallDirs)

find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)

# ==============================================================================
# FFmpeg Setup
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
endif()

# ==============================================================================
# DepthAI Setup
# ==============================================================================
set(DEPTHAI_INSTALL_DIR ${CMAKE_BINARY_DIR}/depthai-install)
set(DEPTHAI_CMAKE_DIR ${DEPTHAI_INSTALL_DIR}/lib/cmake/depthai)

# Check if depthai is already built
if(EXISTS ${DEPTHAI_CMAKE_DIR}/depthaiConfig.cmake)
    message(STATUS "Found pre-built DepthAI at ${DEPTHAI_INSTALL_DIR}")
    set(DEPTHAI_PREBUILT TRUE)
else()
    message(STATUS "DepthAI not found - will be built as external project")
    message(STATUS "  First build takes ~10-15 minutes, subsequent builds are fast")
    set(DEPTHAI_PREBUILT FALSE)
endif()

# Always define the external project (for fresh builds)
ExternalProject_Add(depthai_external
    GIT_REPOSITORY https://github.com/luxonis/depthai-core.git
    GIT_TAG v2.29.0
    GIT_SHALLOW TRUE
    GIT_SUBMODULES_RECURSE TRUE
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${DEPTHAI_INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=Release
        -DBUILD_SHARED_LIBS=OFF
        -DDEPTHAI_BUILD_EXAMPLES=OFF
        -DDEPTHAI_BUILD_TESTS=OFF
        -DDEPTHAI_BUILD_DOCS=OFF
    INSTALL_DIR ${DEPTHAI_INSTALL_DIR}
    UPDATE_COMMAND ""
    # If already built, skip
    EXCLUDE_FROM_ALL ${DEPTHAI_PREBUILT}
)

# ==============================================================================
# Build Plugin (when dependencies are ready)
# ==============================================================================
if(DEPTHAI_PREBUILT AND (FFMPEG_PREBUILT OR FFMPEG_USE_SYSTEM))
    set(depthai_DIR ${DEPTHAI_CMAKE_DIR})
    find_package(depthai REQUIRED CONFIG)
    message(STATUS "Using DepthAI: ${depthai_VERSION}")

    # Find FFmpeg (either local build or system)
    if(FFMPEG_PREBUILT)
        set(ENV{PKG_CONFIG_PATH} "${FFMPEG_INSTALL_DIR}/lib/pkgconfig:$ENV{PKG_CONFIG_PATH}")
        set(CMAKE_PREFIX_PATH ${FFMPEG_INSTALL_DIR} ${CMAKE_PREFIX_PATH})
    endif()
    
    pkg_check_modules(LIBAV REQUIRED IMPORTED_TARGET libavformat libavcodec libavutil)
    message(STATUS "Using FFmpeg: ${LIBAV_VERSION}")
    
    message(STATUS "Building Camera plugin")

    set(CAMERA_PLUGIN_INC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/inc")

    # Build shared core (mp4_writer, camera_plugin)
    add_subdirectory(core)
    add_library(isaac::camera_plugin ALIAS camera_plugin_core)
    
    # Build OAK-D implementation
    add_subdirectory(oakd)
else()
    # Dependencies need to be built first
    set(DEPS_TO_BUILD "")
    if(NOT DEPTHAI_PREBUILT)
        list(APPEND DEPS_TO_BUILD "depthai_external")
    endif()
    if(NOT FFMPEG_PREBUILT AND NOT FFMPEG_USE_SYSTEM)
        list(APPEND DEPS_TO_BUILD "ffmpeg_external")
    endif()

    message(STATUS "Camera plugin dependencies need to be built first")
    message(STATUS "  Run: cmake --build build --target ${DEPS_TO_BUILD}")
    message(STATUS "  Then: cmake -B build && cmake --build build --target camera_plugin_oakd")

    add_custom_target(camera_plugin_oakd
        COMMAND ${CMAKE_COMMAND} -E echo "Dependencies are being built. After completion, run:"
        COMMAND ${CMAKE_COMMAND} -E echo "  cmake -B build  # reconfigure"
        COMMAND ${CMAKE_COMMAND} -E echo "  cmake --build build --target camera_plugin_oakd"
        DEPENDS ${DEPS_TO_BUILD}
    )
endif()
