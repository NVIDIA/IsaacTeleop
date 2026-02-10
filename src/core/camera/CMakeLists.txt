# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

find_package(Threads REQUIRED)

add_library(camera_core STATIC
    camera_plugin.cpp
    rawdata_writer.cpp
)
add_library(isaac::camera_core ALIAS camera_core)

target_include_directories(camera_core INTERFACE inc)

target_link_libraries(camera_core
    PUBLIC
        isaacteleop_schema
        oxr::oxr_core
        pusherio::pusherio
    PRIVATE
        Threads::Threads
)
