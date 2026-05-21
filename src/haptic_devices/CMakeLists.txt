# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(BUILD_PYTHON_BINDINGS)
    add_custom_target(haptic_devices_python ALL
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            "${CMAKE_CURRENT_SOURCE_DIR}"
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/haptic_devices"
        COMMAND ${CMAKE_COMMAND} -E rm -rf
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/haptic_devices/__pycache__"
        COMMAND ${CMAKE_COMMAND} -E rm -f
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/isaacteleop/haptic_devices/CMakeLists.txt"
        COMMENT "Copying haptic_devices Python files to package structure"
    )
endif()
