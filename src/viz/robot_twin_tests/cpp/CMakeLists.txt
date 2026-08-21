# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# The subject of test_symbol_isolation.py: an extension carrying its own private MuJoCo.
# Test-only, and deliberately not staged into the wheel.

cmake_minimum_required(VERSION 3.20)

# isaacteleop_link_mujoco() comes from cmake/Mujoco.cmake, included by
# src/viz/CMakeLists.txt.
pybind11_add_module(mujoco_probe_py mujoco_probe.cpp)

set_target_properties(mujoco_probe_py PROPERTIES
    OUTPUT_NAME "_mujoco_probe"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}")

isaacteleop_link_mujoco(mujoco_probe_py _mujoco_probe)

# mujoco_probe.cpp's loader needs dlopen/dlsym.
target_link_libraries(mujoco_probe_py PRIVATE ${CMAKE_DL_LIBS})

target_compile_options(mujoco_probe_py PRIVATE -Wall -Wextra)
