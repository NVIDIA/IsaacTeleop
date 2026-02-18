# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Pure Python UI module - copy files to build directory

# Copy all Python files to the package directory
add_custom_target(retargeting_engine_ui_python ALL
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}"
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine_ui"
    # Remove unwanted files and directories
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine_ui/__pycache__"
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine_ui/.pytest_cache"
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine_ui/.mypy_cache"
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine_ui/.venv"
    COMMAND ${CMAKE_COMMAND} -E rm -rf
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine_ui/venv"
    COMMAND ${CMAKE_COMMAND} -E rm -f
        "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeting_engine_ui/CMakeLists.txt"
    COMMENT "Copying retargeting_engine_ui Python files to package structure"
)

# Install Python files to the wheel package directory (only .py files, no hidden dirs)
install(
    DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/"
    DESTINATION "python/isaacteleop/retargeting_engine_ui"
    FILES_MATCHING PATTERN "*.py"
    REGEX "/\\." EXCLUDE
)
