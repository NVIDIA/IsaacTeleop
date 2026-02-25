# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)
project(teleop_ros2_examples)

include(${CMAKE_SOURCE_DIR}/cmake/InstallPythonExample.cmake)
install_python_example(DESTINATION examples/teleop_ros2/python
    EXTRA_UV_EXTRA_BUILD_DEPS "nlopt = [\"numpy\"]")

install(FILES README.md Dockerfile
    DESTINATION examples/teleop_ros2
)
