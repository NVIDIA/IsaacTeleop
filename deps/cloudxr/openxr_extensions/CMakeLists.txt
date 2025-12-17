# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_library(teleop_openxr_extensions INTERFACE)
add_library(Teleop::openxr_extensions ALIAS teleop_openxr_extensions)

target_include_directories(teleop_openxr_extensions INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:include>
)

install(FILES XR_NVX1_device_interface.h
    DESTINATION include
)

install(TARGETS teleop_openxr_extensions
    EXPORT TeleopTargets
)
