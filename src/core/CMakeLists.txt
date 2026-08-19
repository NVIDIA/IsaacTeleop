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

#   4. deviceio_session        — DeviceIOSession (wires trackers to live factory)
include(${CMAKE_SOURCE_DIR}/cmake/GenerateTrackers.cmake)
isaac_teleop_generate_trackers()

add_subdirectory(deviceio_base)
add_subdirectory(deviceio_trackers)
add_subdirectory(live_trackers)
add_subdirectory(replay_trackers)
add_subdirectory(deviceio_session)

# Build MCAP library (depends on deviceio for DeviceIOSession and tracker interfaces)
add_subdirectory(mcap)

# CloudXR runtime helper (stages the vendored CloudXR runtime SDK bundle).
# Its pure-Python source lives in src/python/isaacteleop/cloudxr/, as does the
# retargeting engine's, the rig launcher's and the session manager's.
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

    # CloudXR tests (Python — requires the built wheel from python/)
    if(BUILD_PYTHON_BINDINGS)
        add_subdirectory(cloudxr_tests)
    endif()

    # Rig launcher tests (Python)
    if(BUILD_PYTHON_BINDINGS)
        add_subdirectory(rig_tests)
    endif()

    # MCAP tests (C++)
    add_subdirectory(mcap_tests/cpp)

    # Replay DeviceIO session tests (C++)
    add_subdirectory(replay_deviceio_session_tests/cpp)

    # Live trackers tests (C++)
    add_subdirectory(live_trackers_tests/cpp)
endif()
