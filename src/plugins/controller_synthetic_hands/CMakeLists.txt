# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# If this is being built standalone, declare a project
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(controller_synthetic_hands VERSION 1.0.0 LANGUAGES CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

# Create executable
add_executable(controller_synthetic_hands
    controller_synthetic_hands.cpp
    session.cpp
    controllers.cpp
    hand_generator.cpp
    hand_injector.cpp
)

# Include directories
target_include_directories(controller_synthetic_hands PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

# Find required system libraries for static linking
find_package(Threads REQUIRED)

# Link against OpenXR from submodule (statically linked)
# When statically linking, we need to include system dependencies
target_link_libraries(controller_synthetic_hands PRIVATE
    OpenXR::openxr_loader
    ${CMAKE_DL_LIBS}      # For dlopen/dlsym
    Threads::Threads      # For pthread
)

# Installation - install to devices subdirectory
install(TARGETS controller_synthetic_hands
    RUNTIME DESTINATION devices
)

# Install README alongside the binary
install(FILES README.md
    DESTINATION devices
    OPTIONAL
)

