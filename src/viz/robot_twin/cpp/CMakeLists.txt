# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# `_robot_twin` -- MuJoCo's own OpenGL renderer, read back into CUDA-visible buffers for
# viz::ProjectionLayer. Output lands in
# ${CMAKE_BINARY_DIR}/python_package/<cfg>/isaacteleop/viz/robot/, beside the Python
# staged by src/python/CMakeLists.txt.
#
# Protocol-only linkage: no viz:: target, because __cuda_array_interface__ is the whole
# interface. Do not pin them together.
#
# No OpenGL on the link line either -- gl.hpp resolves through eglGetProcAddress and
# gl_context.cpp dlopens libEGL, so the wheel carries no NEEDED entry for either. Only
# EGL's headers are a build dependency; CheckBuildDeps.cmake asks for them.

cmake_minimum_required(VERSION 3.20)

find_package(CUDAToolkit REQUIRED)

pybind11_add_module(robot_twin_py
    robot_twin_bindings.cpp
    gl.cpp
    gl_context.cpp
    gl_readback.cpp
    mj_api.cpp
    mj_guard.cpp
    scene.cpp
    scene_renderer.cpp
    frames.hpp
    gl.hpp
    gl_context.hpp
    gl_functions.inc
    glcamera.hpp
    gl_readback.hpp
    mj_api.hpp
    mj_functions.inc
    mj_guard.hpp
    scene.hpp
    scene_renderer.hpp
)

target_link_libraries(robot_twin_py
    PRIVATE
        # Matches viz_core: no runtime libcudart.so on a driver-only machine.
        CUDA::cudart_static
        # gl.cpp's and gl_context.cpp's loaders need dlopen/dlsym.
        ${CMAKE_DL_LIBS}
)

# MuJoCo's headers, libisaacteleop_mujoco.so staged beside the module for mj_api.cpp to
# dlopen, and nothing exported but PyInit__robot_twin -- see deps/third_party/Mujoco.cmake.
# Deliberately not a link: an undefined mj* would let a user's own libmujoco answer instead
# of ours, silently.
isaacteleop_link_mujoco(robot_twin_py _robot_twin)

target_compile_options(robot_twin_py PRIVATE -Wall -Wextra)

set_target_properties(robot_twin_py PROPERTIES
    OUTPUT_NAME "_robot_twin"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/viz/robot"
)
