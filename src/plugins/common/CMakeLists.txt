# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Static library for common plugin code
add_library(teleop_plugin_common STATIC
    controllers.cpp
    hand_injector.cpp
    session.cpp
)

# Dependencies
target_link_libraries(teleop_plugin_common
    PUBLIC
        Teleop::openxr_extensions
        OpenXR::openxr_loader
)

# Include directories
target_include_directories(teleop_plugin_common
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
)

# Alias
add_library(Teleop::plugin_common ALIAS teleop_plugin_common)

