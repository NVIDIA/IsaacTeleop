# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Pure Python module - copy files to build directory

# Copy all Python files to the package directory
add_custom_target(retargeting_engine_python ALL
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}"
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine"
    # Remove unwanted files and directories
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine/__pycache__"
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine/.pytest_cache"
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine/.mypy_cache"
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine/.venv"
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine/venv"
    COMMAND ${CMAKE_COMMAND} -E rm -f
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine/CMakeLists.txt"
    COMMAND ${CMAKE_COMMAND} -E rm -f
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine/uv.lock"
    COMMENT "Copying retargeting_engine Python files to package structure"
)

# Install Python files to the wheel package directory (only .py files, no hidden dirs)
install(
    DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/"
    DESTINATION "python/isaacteleop/retargeting_engine"
    FILES_MATCHING PATTERN "*.py"
    REGEX "/\\." EXCLUDE
)
