# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Python bindings for Televiz — _viz.so + isaacteleop.viz package.
# Output lands in ${CMAKE_BINARY_DIR}/python_package/<cfg>/isaacteleop/viz/
# next to the __init__.py staged by src/core/python/CMakeLists.txt.

cmake_minimum_required(VERSION 3.20)

# Bindings are split per-sub-module to mirror the C++ dep DAG
# (core → layers → session). viz_bindings.cpp is the PYBIND11_MODULE
# entry point and calls into the bind_*(m) helpers in the others.
pybind11_add_module(viz_py
    viz_bindings.cpp
    bind_core.cpp
    bind_layers.cpp
    bind_session.cpp
)

target_link_libraries(viz_py
    PRIVATE
        viz::session
        viz::layers
        viz::core
)

set_target_properties(viz_py PROPERTIES
    OUTPUT_NAME "_viz"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/viz"
)

# Generate the .pyi stub for isaacteleop.viz._viz using the same
# `uv run --project ${CMAKE_BINARY_DIR}/stubgen` venv that
# src/core/python/CMakeLists.txt creates for the rest of the modules.
# Best-effort: if the stubgen venv isn't ready yet (e.g. first
# configure, or BUILD_PYTHON_BINDINGS=ON without a corresponding
# python_package target), we still want viz_py itself to succeed —
# stubs are an IDE convenience, not a build requirement.
add_custom_command(TARGET viz_py POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E echo "Generating isaacteleop.viz stub..."
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/stubgen"
    COMMAND ${CMAKE_COMMAND} -E copy
        "${CMAKE_SOURCE_DIR}/src/core/python/stubgen_pyproject.toml"
        "${CMAKE_BINARY_DIR}/stubgen/pyproject.toml"
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen"
        --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${CMAKE_SOURCE_DIR}/src/core/python/generate_stubs.py"
        isaacteleop.viz._viz
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    VERBATIM
)
