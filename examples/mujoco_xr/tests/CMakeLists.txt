# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# mujoco_xr tests. Each test_*.py registers as its own ctest entry under the
# `mujoco_xr` label -- same shape as examples/camera_viz/tests/CMakeLists.txt.
#
# All of them are unit-level and need NO GPU, no headset, no CloudXR runtime
# and no window system: frame conventions, the projection matrix, the clock, the
# scene catalogue, the IK solver, the clutch and the ghost overlay. That is the
# whole of it, deliberately -- a test that needs hardware only one developer has
# reports green by skipping, and examples have no CI to run it in anyway
# (NVIDIA/IsaacTeleop#880). The GPU-backed kOffscreen render test that used to
# live here was removed for exactly that reason; the Vulkan -> CUDA -> submit
# path is now covered nowhere, and README.md says so under
# "Not verified anywhere in CI or on a developer desktop".

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
