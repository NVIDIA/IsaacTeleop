# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Create executable
add_executable(controller_synthetic_hands
    controller_synthetic_hands.cpp
    synthetic_hands_plugin.cpp
    hand_generator.cpp
)

# Include directories
target_include_directories(controller_synthetic_hands PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

# Find required system libraries for static linking
find_package(Threads REQUIRED)

# Link against OpenXR (fetched via CMake FetchContent - statically linked)
# When statically linking, we need to include system dependencies
target_link_libraries(controller_synthetic_hands PRIVATE
    Teleop::plugin_common # Transitive dependency on OpenXR::openxr_loader and Teleop::openxr_extensions
    ${CMAKE_DL_LIBS}      # For dlopen/dlsym
    Threads::Threads      # For pthread
)

# Installation - install to plugins/controller_synthetic_hands subdirectory
install(TARGETS controller_synthetic_hands
    RUNTIME DESTINATION plugins/controller_synthetic_hands
)

# Install metadata and README alongside the binary
install(FILES plugin.yaml README.md
    DESTINATION plugins/controller_synthetic_hands
)
