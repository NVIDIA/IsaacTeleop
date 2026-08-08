# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# mujoco_xr tests. Each test_*.py registers as its own ctest entry under the
# `mujoco_xr` label -- same shape as examples/camera_viz/tests/CMakeLists.txt.
#
# Keep every test here unit-level: no GPU, no headset, no CloudXR runtime, no
# window system. A test gated on hardware one developer has reports green by
# skipping, and examples have no CI to run it in (NVIDIA/IsaacTeleop#880). The
# cost is that the Vulkan -> CUDA -> submit path is covered nowhere, which
# README.md states under "Not verified anywhere in CI or on a developer
# desktop".

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
    # Resolves isaacteleop only; the example's own package is reached from the
    # source tree by conftest.py.
    #
    # If a second root is ever added: CMake's ENVIRONMENT property is a
    # semicolon-separated list, so two "PYTHONPATH=..." elements silently
    # produce two entries and only the last survives. Join additional roots with
    # ':' inside one quoted string.
    set_tests_properties("mujoco_xr_${test_name}" PROPERTIES
        ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
        LABELS "mujoco_xr"
    )
endforeach()
