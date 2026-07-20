# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Rig Launcher Python Module (pure Python)

# Determine output directory for wheel packaging
set(RIG_OUTPUT_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/rig")

# List of Python files to copy
set(RIG_PYTHON_FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/__init__.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/__main__.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/config.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/launcher.py"
)

# Copy Python files to output directory during build
foreach(PYTHON_FILE ${RIG_PYTHON_FILES})
    get_filename_component(FILE_NAME ${PYTHON_FILE} NAME)
    set(OUTPUT_PATH "${RIG_OUTPUT_DIR}/${FILE_NAME}")

    add_custom_command(
        OUTPUT "${OUTPUT_PATH}"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${RIG_OUTPUT_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy "${PYTHON_FILE}" "${OUTPUT_PATH}"
        DEPENDS "${PYTHON_FILE}"
        COMMENT "Copying ${FILE_NAME} to rig package"
    )

    list(APPEND RIG_OUTPUT_FILES "${OUTPUT_PATH}")
endforeach()

# Create custom target to ensure all files are copied
add_custom_target(rig_python ALL
    DEPENDS ${RIG_OUTPUT_FILES}
    COMMENT "Building rig Python module"
)
