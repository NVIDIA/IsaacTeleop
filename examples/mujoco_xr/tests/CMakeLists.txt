# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# mujoco_xr tests. Each test_*.py registers as its own ctest entry under the
# `mujoco_xr` label -- same shape as examples/camera_viz/tests/CMakeLists.txt.
#
# Most are unit-level (frame conventions, the projection matrix, the clock),
# but test_offscreen_render.py is not: it builds a real GPU-backed kOffscreen
# VizSession and runs the whole Vulkan -> CUDA -> submit path, skipping with a
# reason when there is no usable device. What is deliberately NOT here is
# anything requiring a HEADSET or a CloudXR runtime, because a
# permanently-skipping test reports green while covering nothing. Same split
# README.md states under "Not verified anywhere in CI".

file(GLOB TEST_FILES
    RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/test_*.py"
)

foreach(test_file ${TEST_FILES})
    get_filename_component(test_name "${test_file}" NAME_WE)
    add_test(
        NAME "mujoco_xr_${test_name}"
        COMMAND uv run --python ${ISAAC_TELEOP_PYTHON_VERSION} --extra dev
            pytest -v --tb=short "${test_file}"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )
    # One entry, resolving isaacteleop only -- exactly as
    # examples/camera_viz/tests/CMakeLists.txt does. The example's own
    # `mujoco_xr` package is reached from the source tree by conftest.py, which
    # also keeps a bare `pytest` in this directory working.
    #
    # Trap, if a second root is ever added here: CMake's ENVIRONMENT property is
    # a SEMICOLON-separated list, so two "PYTHONPATH=..." elements (or a ';'
    # join) silently produce two entries and only the last survives. Join
    # additional roots with ':' inside ONE quoted string.
    set_tests_properties("mujoco_xr_${test_name}" PROPERTIES
        ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
        LABELS "mujoco_xr"
    )
endforeach()
