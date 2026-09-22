# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Reads the wheel built by the python_wheel target, which only exists in the
# classic `cmake -B build` flow -- under scikit-build-core pip owns assembly and
# ${CMAKE_BINARY_DIR}/wheels is never written.

file(GLOB TEST_FILES
    RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/test_*.py"
)

foreach(test_file ${TEST_FILES})
    get_filename_component(test_name "${test_file}" NAME_WE)

    add_test(
        NAME "packaging_${test_name}"
        COMMAND uv run --python ${ISAAC_TELEOP_PYTHON_VERSION} --extra dev pytest -v --tb=short "${test_file}"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )

    set_tests_properties("packaging_${test_name}" PROPERTIES
        ENVIRONMENT "ISAAC_TELEOP_WHEELS_DIR=${CMAKE_BINARY_DIR}/wheels"
    )
endforeach()
