# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Static library for plugin utilities
add_library(teleop_plugin_utils STATIC
    controllers.cpp
    hand_injector.cpp
    session.cpp
    inc/plugin_utils/controllers.hpp
    inc/plugin_utils/hand_injector.hpp
    inc/plugin_utils/math.hpp
    inc/plugin_utils/session.hpp
)

# Dependencies
target_link_libraries(teleop_plugin_utils
    PUBLIC
    Teleop::openxr_extensions
    OpenXR::openxr_loader
)

# Include directories
target_include_directories(teleop_plugin_utils
    PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# Alias
add_library(Teleop::plugin_utils ALIAS teleop_plugin_utils)

# Tests
option(BUILD_PLUGIN_UTILS_TESTS "Build plugin utils tests" ON)
if(BUILD_PLUGIN_UTILS_TESTS)
    add_subdirectory(tests)
endif()
