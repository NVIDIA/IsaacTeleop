# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Interface library for OpenXR extensions
add_library(teleop_openxr_extensions INTERFACE)
add_library(Teleop::openxr_extensions ALIAS teleop_openxr_extensions)

# Associate the include directory with the target
target_include_directories(teleop_openxr_extensions INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:include>
)

# Install the headers
install(DIRECTORY openxr
    DESTINATION include
)

# Install the target export (optional, but good practice)
install(TARGETS teleop_openxr_extensions
    EXPORT TeleopTargets
)

