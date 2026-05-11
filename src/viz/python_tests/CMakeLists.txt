# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Python tests for the isaacteleop.viz bindings.
#
# Each test_*.py here registers as a separate CTest entry under the
# label "viz_python" so it can be filtered via -L. Tests that need a
# GPU mark themselves with pytest.skip if cuda isn't available, so
# CI-without-GPU still passes (just with SKIPs).

file(GLOB TEST_FILES
    RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/test_*.py"
)

foreach(test_file ${TEST_FILES})
    get_filename_component(test_name "${test_file}" NAME_WE)
    add_test(
        NAME "viz_python_${test_name}"
        COMMAND uv run --python ${ISAAC_TELEOP_PYTHON_VERSION} --extra dev
            pytest -v --tb=short "${test_file}"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )
    set_tests_properties("viz_python_${test_name}" PROPERTIES
        ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
        LABELS "viz_python"
    )
endforeach()
