# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# robot_viz tests. Each test_*.py registers as its own ctest entry under the
# `robot_viz` label -- same shape as examples/camera_viz/tests/CMakeLists.txt.
#
# Keep tests here unit-level -- no GPU, no headset, no CloudXR runtime, no
# window system -- because a test gated on hardware one developer has reports
# green by skipping, and examples have no CI to run it in
# (NVIDIA/IsaacTeleop#880). The renderer's own GPU test lives with the
# renderer, in src/viz/robot_twin_tests/.

file(GLOB TEST_FILES
    RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/test_*.py"
)

foreach(test_file ${TEST_FILES})
    get_filename_component(test_name "${test_file}" NAME_WE)
    add_test(
        NAME "robot_viz_${test_name}"
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
    set_tests_properties("robot_viz_${test_name}" PROPERTIES
        ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
        LABELS "robot_viz"
    )
endforeach()
