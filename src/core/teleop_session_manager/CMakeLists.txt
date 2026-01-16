# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# TeleopSessionManager Python Module

# Determine output directory for wheel packaging
set(TELEOP_SESSION_MANAGER_OUTPUT_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/teleop_session_manager")

# List of Python files to copy
set(TELEOP_SESSION_MANAGER_PYTHON_FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/python/__init__.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/python/config.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/python/teleop_session.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/python/helpers.py"
)

# Copy Python files to output directory during build
foreach(PYTHON_FILE ${TELEOP_SESSION_MANAGER_PYTHON_FILES})
    get_filename_component(FILE_NAME ${PYTHON_FILE} NAME)
    set(OUTPUT_PATH "${TELEOP_SESSION_MANAGER_OUTPUT_DIR}/${FILE_NAME}")
    
    add_custom_command(
        OUTPUT "${OUTPUT_PATH}"
        COMMAND ${CMAKE_COMMAND} -E copy "${PYTHON_FILE}" "${OUTPUT_PATH}"
        DEPENDS "${PYTHON_FILE}"
        COMMENT "Copying ${FILE_NAME} to teleop_session_manager package"
    )
    
    list(APPEND TELEOP_SESSION_MANAGER_OUTPUT_FILES "${OUTPUT_PATH}")
endforeach()

# Create custom target to ensure all files are copied
add_custom_target(teleop_session_manager_python ALL
    DEPENDS ${TELEOP_SESSION_MANAGER_OUTPUT_FILES}
    COMMENT "Building teleop_session_manager Python module"
)

# Install Python files for direct installation (non-wheel)
install(FILES
    python/__init__.py
    python/config.py
    python/teleop_session.py
    python/helpers.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/teleop_session_manager
)

message(STATUS "TeleopSessionManager Python package configured for installation")

