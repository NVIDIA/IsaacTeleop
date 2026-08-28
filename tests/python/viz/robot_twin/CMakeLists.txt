# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# The robot twin's backend: the frame and projection conventions, the SceneTwin API, the
# GPU readback, and the property the packaging rests on -- its MuJoCo is private, so a
# user's own `mujoco` (any version, or none) cannot collide with it.
#
# Its own leaf rather than a file in the parent: the pyproject here pins a mujoco that
# must NOT be the one deps/third_party builds, and model.xml is a fixture beside it.

file(GLOB TEST_FILES
    RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/test_*.py"
)

# --extra dev installs a mujoco whose version differs from ISAACTELEOP_MUJOCO_VERSION, so
# the tests can tell the two copies apart by what they report. That and
# ISAACTELEOP_ROBOT_TWIN_DIR are read only by test_symbol_isolation.py, which skips
# without them; they are set for every test here so a bare `pytest` and ctest differ in
# nothing but the staged PYTHONPATH.
foreach(test_file ${TEST_FILES})
    get_filename_component(test_name "${test_file}" NAME_WE)
    add_test(
        NAME "viz_python_robot_twin_${test_name}"
        COMMAND uv run --python ${ISAAC_TELEOP_PYTHON_VERSION} --extra dev
            pytest -v --tb=short "${test_file}"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )
    # One quoted string: CMake's ENVIRONMENT is a semicolon-separated list, so two
    # "PYTHONPATH=..." elements would silently leave only the last.
    set_tests_properties("viz_python_robot_twin_${test_name}" PROPERTIES
        ENVIRONMENT
            "PYTHONPATH=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>;ISAACTELEOP_MUJOCO_VERSION=${ISAACTELEOP_MUJOCO_VERSION};ISAACTELEOP_ROBOT_TWIN_DIR=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/viz/robot"
        LABELS "viz_python"
    )
endforeach()
