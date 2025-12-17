# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Plugin Manager library
add_library(teleop_plugin_manager STATIC
    plugin.cpp
    plugin_manager.cpp
)

# Include directory
target_include_directories(teleop_plugin_manager INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# Set standard C++17
target_compile_features(teleop_plugin_manager PUBLIC cxx_std_17)

# Link dependencies
find_package(Threads REQUIRED)
target_link_libraries(teleop_plugin_manager
    PUBLIC
        Threads::Threads
    PRIVATE
        yaml-cpp::yaml-cpp
)

# Install
install(TARGETS teleop_plugin_manager
    EXPORT teleop_plugin_manager_targets
    ARCHIVE DESTINATION lib
    LIBRARY DESTINATION lib
    RUNTIME DESTINATION bin
)

install(DIRECTORY inc/
    DESTINATION include
)

