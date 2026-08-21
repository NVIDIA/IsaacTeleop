# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Pure Python; there is nothing here to compile. Registers the example's tests, which
# need the staged isaacteleop -- including the robot twin's backend, hence the gate at
# the root rather than here.

cmake_minimum_required(VERSION 3.20)

if(BUILD_TESTING)
    add_subdirectory(tests)
endif()
