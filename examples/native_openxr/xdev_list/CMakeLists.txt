# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Main test executable
add_executable(xdev_list main.cpp)

target_include_directories(
	xdev_list PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/.. ${OpenXR_INCLUDE_DIRS}
	)

target_link_libraries(xdev_list PRIVATE examples_common Teleop::openxr_extensions)

# Set output name
set_target_properties(xdev_list PROPERTIES OUTPUT_NAME "xdev_list")

# Install the xdev_list executable and README
install(TARGETS xdev_list RUNTIME DESTINATION examples/native_openxr/xdev_list)
