# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_library(teleop_openxr_extensions INTERFACE)
add_library(Teleop::openxr_extensions ALIAS teleop_openxr_extensions)

target_include_directories(teleop_openxr_extensions INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
)

install(FILES
    openxr_extension_helpers.h
    XR_NVX1_device_interface.h
    XR_NVX1_tensor_data.h
    XR_NVX1_push_tensor.h
    DESTINATION include
)
