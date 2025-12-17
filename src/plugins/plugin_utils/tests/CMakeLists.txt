# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Math tests (Compile-time + Runtime wrapper)
add_executable(test_math test_math.cpp)
target_link_libraries(test_math PRIVATE Catch2::Catch2WithMain OpenXR::headers)
target_include_directories(test_math PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../inc)

# Runtime tests (Mocked)
# We compile the sources directly here to avoid linking the OpenXR loader which is linked by the main library
add_executable(test_plugin_utils_runtime
    test_runtime.cpp
    mock_openxr.cpp
    ../controllers.cpp
    ../session.cpp
    ../hand_injector.cpp
)

# We need OpenXR headers and extension definitions
target_link_libraries(test_plugin_utils_runtime PRIVATE Catch2::Catch2WithMain OpenXR::headers Teleop::openxr_extensions)
target_include_directories(test_plugin_utils_runtime PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../inc)

# Register tests
# Catch2 provides a helper to register tests, but simple add_test works too
include(CTest)
catch_discover_tests(test_math)
catch_discover_tests(test_plugin_utils_runtime)
