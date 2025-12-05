# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# Retargeting Engine - Python Package
# ==============================================================================

# This CMakeLists.txt handles installation of the Python-only retargeting engine
# No C++ bindings are needed for this simplified module

# Determine output directory
set(RETARGETING_ENGINE_OUTPUT_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/teleopcore/retargeting_engine")

# Explicitly list the source directories to avoid picking up venv files
set(RETARGETING_ENGINE_SOURCE_DIRS
    "${CMAKE_CURRENT_SOURCE_DIR}/interface"
    "${CMAKE_CURRENT_SOURCE_DIR}/tensor_types"
    "${CMAKE_CURRENT_SOURCE_DIR}/examples"
    "${CMAKE_CURRENT_SOURCE_DIR}/sources"
    "${CMAKE_CURRENT_SOURCE_DIR}/retargeters"
)

# Collect Python files from specific directories only
set(RETARGETING_ENGINE_PYTHON_FILES)
foreach(SOURCE_DIR ${RETARGETING_ENGINE_SOURCE_DIRS})
    file(GLOB_RECURSE DIR_PYTHON_FILES "${SOURCE_DIR}/*.py")
    list(APPEND RETARGETING_ENGINE_PYTHON_FILES ${DIR_PYTHON_FILES})
endforeach()

# Add the root __init__.py
list(APPEND RETARGETING_ENGINE_PYTHON_FILES "${CMAKE_CURRENT_SOURCE_DIR}/__init__.py")

# Copy Python files to output directory during build
foreach(PYTHON_FILE ${RETARGETING_ENGINE_PYTHON_FILES})
    # Get relative path
    file(RELATIVE_PATH REL_PATH "${CMAKE_CURRENT_SOURCE_DIR}" "${PYTHON_FILE}")
    
    # Configure output path
    set(OUTPUT_PATH "${RETARGETING_ENGINE_OUTPUT_DIR}/${REL_PATH}")
    
    # Add custom command to copy file
    add_custom_command(
        OUTPUT "${OUTPUT_PATH}"
        COMMAND ${CMAKE_COMMAND} -E copy "${PYTHON_FILE}" "${OUTPUT_PATH}"
        DEPENDS "${PYTHON_FILE}"
        COMMENT "Copying ${REL_PATH} to retargeting_engine package"
    )
    
    list(APPEND RETARGETING_ENGINE_OUTPUT_FILES "${OUTPUT_PATH}")
endforeach()

# Create custom target to ensure all files are copied
add_custom_target(retargeting_engine_python ALL
    DEPENDS ${RETARGETING_ENGINE_OUTPUT_FILES}
    COMMENT "Building retargeting_engine Python module"
)

# ==============================================================================
# Testing and Type Checking
# ==============================================================================

# Custom target to run type checking using mypy
add_custom_target(typecheck_retargeting_engine
    COMMAND uv run --python ${TELEOPCORE_PYTHON_VERSION} --with mypy mypy --ignore-missing-imports .
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Running type checking with mypy on retargeting engine (Python ${TELEOPCORE_PYTHON_VERSION})"
)

# Custom target to run tests using uv with the correct Python version
# Install test dependencies from pyproject.toml [project.optional-dependencies.test]
add_custom_target(test_retargeting_engine
    COMMAND uv run --python ${TELEOPCORE_PYTHON_VERSION} --extra test pytest -v
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Running retargeting engine tests with Python ${TELEOPCORE_PYTHON_VERSION}"
)

# ==============================================================================
# Installation
# ==============================================================================

# Install Python files for package distribution
install(
    DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/"
    DESTINATION "python/teleopcore/retargeting_engine"
    FILES_MATCHING PATTERN "*.py"
    PATTERN "tests" EXCLUDE
    PATTERN "__pycache__" EXCLUDE
    PATTERN ".pytest_cache" EXCLUDE
    PATTERN ".venv" EXCLUDE
    PATTERN "venv" EXCLUDE
)


