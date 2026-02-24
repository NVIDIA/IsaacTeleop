# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Options
option(BUILD_PYTHON_BINDINGS "Build Python bindings" ON)

# Generated headers from FlatBuffer schemas with additional utilities.
add_subdirectory(schema)

# Build OXR Utils first - header-only utilities (no dependencies)
add_subdirectory(oxr_utils)

# Build Plugin Manager
add_subdirectory(plugin_manager)

# Build OXR library (depends on oxr_utils for types)
add_subdirectory(oxr)

# Build PusherIO library (depends on oxr for session management)
add_subdirectory(pusherio)

# Build DEVICEIO library first (depends on oxr_utils for types)
add_subdirectory(deviceio)

# Build MCAP library (depends on deviceio for DeviceIOSession and tracker interfaces)
add_subdirectory(mcap)

# Build Retargeting Engine (pure Python module)
add_subdirectory(retargeting_engine)

# Build Retargeting Engine UI (pure Python module with optional dependencies)
add_subdirectory(retargeting_engine_ui)

# Build TeleopSessionManager (pure Python module)
add_subdirectory(teleop_session_manager)

# CloudXR runtime helper (pure Python, docker-less)
add_subdirectory(cloudxr)

# Python wheel packaging (combines both modules)
if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()

# ==============================================================================
# Tests
# ==============================================================================

if(BUILD_TESTING)
    # Schema tests (C++ and Python)
    add_subdirectory(schema_tests)

    # Retargeting engine tests (Python)
    add_subdirectory(retargeting_engine_tests)

    # Teleop session manager tests (Python)
    add_subdirectory(teleop_session_manager_tests)

    # MCAP tests (C++)
    add_subdirectory(mcap_tests/cpp)
endif()
