# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_library(orbbec_camera_core STATIC
    orbbec_camera.cpp
    preview.cpp
    preview.hpp
    inc/orbbec_camera/orbbec_camera.hpp
)

find_package(PkgConfig REQUIRED)
pkg_check_modules(ORBBEC_PREVIEW REQUIRED IMPORTED_TARGET sdl2 libavcodec libavutil libswscale)

target_include_directories(orbbec_camera_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(orbbec_camera_core
    PUBLIC
        isaacteleop_schema
    PRIVATE
        ob::OrbbecSDK
        mcap::mcap_core
        oxr::oxr_core
        pusherio::pusherio
        PkgConfig::ORBBEC_PREVIEW
)

add_library(orbbec::camera_core ALIAS orbbec_camera_core)
