# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(BUILD_PYTHON_BINDINGS)
    add_custom_target(retargeters_python ALL
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            "${CMAKE_CURRENT_SOURCE_DIR}"
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeters"
        COMMAND ${CMAKE_COMMAND} -E rm -rf
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeters/__pycache__"
        COMMAND ${CMAKE_COMMAND} -E rm -rf
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeters/G1/__pycache__"
        COMMAND ${CMAKE_COMMAND} -E rm -f
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeters/CMakeLists.txt"
        COMMAND ${CMAKE_COMMAND} -E rm -f
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/retargeters/README.md"
        COMMENT "Copying retargeters Python files to package structure"
    )
endif()
