# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# logging_config Python Tests
# ==============================================================================

# Discover and add individual Python tests
# This makes each test show up separately in CTest output

# The routing matrix has a C++ half: log_bridge_emit_record logs one record
# through isaacteleop::Logger and exits, so the suite can point a real receiver
# at a real C++ sender instead of asserting each end against its own idea of the
# wire format. Absent when this suite is run straight from a source checkout,
# which is why the tests using it skip rather than fail without it.
set(LOGGING_CONFIG_TEST_ENVIRONMENT
    "PYTHONPATH=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
    "ISAACTELEOP_LOG_EMITTER=$<TARGET_FILE:log_bridge_emit_record>"
)

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
        NAME "logging_config_${test_name}"
        COMMAND uv run --python ${ISAAC_TELEOP_PYTHON_VERSION} --extra dev pytest -v --tb=short "${test_file}"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )

    # Set the environment to ensure the built package is available
    set_tests_properties("logging_config_${test_name}" PROPERTIES
        ENVIRONMENT "${LOGGING_CONFIG_TEST_ENVIRONMENT}"
    )
endforeach()
