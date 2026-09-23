# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# Logging System Python Tests (both halves)
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
        NAME "logging_config_${test_name}"
        COMMAND uv run --python ${ISAAC_TELEOP_PYTHON_VERSION} --extra dev pytest -v --tb=short "${test_file}"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )

    # Set the environment to ensure the built package is available. This process
    # becomes a session leader of its own the moment it imports isaaccapture, so
    # give it a log directory in the build tree rather than the shared default;
    # LOG_BRIDGE_TEST_EMITTER is the out-of-process C++ half of the suite.
    set_tests_properties("logging_config_${test_name}" PROPERTIES
        ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/python_package/$<CONFIG>;ISAACCAPTURE_LOG_DIR=${CMAKE_CURRENT_BINARY_DIR}/logs;LOG_BRIDGE_TEST_EMITTER=$<TARGET_FILE:log_bridge_test_emitter>"
    )
endforeach()
