# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_subdirectory(core)

if(BUILD_EXAMPLE_TELEOP_ROS2)
    add_subdirectory(examples/teleop_ros2)
endif()

if(BUILD_VIZ AND BUILD_PYTHON_BINDINGS)
    add_subdirectory(viz)
endif()

if(BUILD_EXAMPLES AND BUILD_VIZ)
    add_subdirectory(examples)
endif()
