# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# Retargeting Engine Python Tests
# ==============================================================================

# Discover and add individual Python tests
# This makes each test show up separately in CTest output

# First, find all test files (only in this directory, not recursively)
file(GLOB TEST_FILES 
    RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/test_*.py"
)

# Add each test file as a separate CTest test
foreach(test_file ${TEST_FILES})
    # Get test name from filename (remove .py and path)
    get_filename_component(test_name "${test_file}" NAME_WE)
    
    # Add the test
    add_test(
        NAME "retargeting_${test_name}"
        COMMAND uv run --python ${ISAAC_TELEOP_PYTHON_VERSION} --extra dev pytest -v --tb=short "${test_file}"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )
    
    # Set the environment to ensure the built package is available
    set_tests_properties("retargeting_${test_name}" PROPERTIES
        ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
    )
endforeach()

# Add mypy type checking test
add_test(
    NAME "retargeting_mypy_type_check"
    COMMAND uv run --python ${ISAAC_TELEOP_PYTHON_VERSION} --extra dev 
        mypy --config-file pyproject.toml
        "${CMAKE_SOURCE_DIR}/src/core/retargeting_engine/python"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
)

# Set the environment to ensure the built package is available for type checking
set_tests_properties("retargeting_mypy_type_check" PROPERTIES
    ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
)

