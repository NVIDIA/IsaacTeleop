# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

find_package(Threads REQUIRED)

add_library(camera_plugin_core STATIC
    camera_plugin.cpp
    rawdata_writer.cpp
)
add_library(isaac::camera_plugin ALIAS camera_plugin_core)

target_include_directories(camera_plugin_core PUBLIC inc)

target_link_libraries(camera_plugin_core
    PUBLIC
        Teleop::plugin_utils
        OpenXR::openxr_loader
    PRIVATE
        Teleop::openxr_extensions
        Threads::Threads
)
