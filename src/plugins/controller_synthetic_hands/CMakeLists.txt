# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Create executable
add_executable(controller_synthetic_hands
    controller_synthetic_hands.cpp
    synthetic_hands_plugin.cpp
    hand_generator.cpp
    inc/controller_synthetic_hands/synthetic_hands_plugin.hpp
    inc/controller_synthetic_hands/hand_generator.hpp
)

target_include_directories(controller_synthetic_hands PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/inc
)

find_package(Threads REQUIRED)

target_link_libraries(controller_synthetic_hands PRIVATE
    Teleop::plugin_utils
    deviceio::deviceio_core
    oxr::oxr_core
    oxr::oxr_utils
    OpenXR::openxr_loader
    Teleop::openxr_extensions
    ${CMAKE_DL_LIBS}      # For dlopen/dlsym
    Threads::Threads      # For pthread
)

install(TARGETS controller_synthetic_hands
    RUNTIME DESTINATION plugins/controller_synthetic_hands
)

install(FILES plugin.yaml README.md
    DESTINATION plugins/controller_synthetic_hands
)
