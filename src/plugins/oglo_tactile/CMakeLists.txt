# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# OGLO Tactile Glove Plugin (BLE)
# ==============================================================================
# Reads OGLO tactile gloves (80 taxels + 6-axis IMU per hand) over BLE and pushes
# them via OpenXR SchemaPusher for a host tracker to record. Linux only (BlueZ).
#
# Enable with: cmake -B build -DBUILD_PLUGIN_OGLO=ON
#
# BLE backend: the plugin talks to BlueZ directly over libdbus (AFL-2.1,
# permissive) — no copyleft dependency, works out of the box on any Linux host
# with the BlueZ daemon. The transport sits behind the OgloBleClient interface,
# so an alternative backend can be dropped in via make_ble_client() if needed.
#
# Prerequisites (Linux): BlueZ daemon + libdbus development headers
#   sudo apt install libdbus-1-dev
# ==============================================================================

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(STATUS "Skipping oglo_tactile plugin (Linux only)")
    return()
endif()

include(FetchContent)

# ------------------------------------------------------------------------------
# nlohmann/json — parse the device Config characteristic (MIT, header-only).
# ------------------------------------------------------------------------------
FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.11.3
    GIT_SHALLOW TRUE
)
set(JSON_BuildTests OFF CACHE INTERNAL "")
FetchContent_MakeAvailable(nlohmann_json)

# ------------------------------------------------------------------------------
# BLE backend: BlueZ over the system libdbus (AFL-2.1, permissive).
# ------------------------------------------------------------------------------
find_package(PkgConfig REQUIRED)
pkg_check_modules(DBUS REQUIRED IMPORTED_TARGET dbus-1)

add_executable(oglo_tactile_plugin
    main.cpp
    oglo_tactile_plugin.cpp
    oglo_glove_sink.cpp
    oglo_config.cpp
    oglo_packet_parser.cpp
    ble/oglo_ble_client.cpp
    ble/oglo_ble_client_bluez.cpp
)

target_include_directories(oglo_tactile_plugin PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

target_link_libraries(oglo_tactile_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
    nlohmann_json::nlohmann_json
    PkgConfig::DBUS
)

set_target_properties(oglo_tactile_plugin PROPERTIES INSTALL_RPATH "$ORIGIN")

install(TARGETS oglo_tactile_plugin RUNTIME DESTINATION plugins/oglo_tactile)
install(FILES plugin.yaml README.md DESTINATION plugins/oglo_tactile)

# ------------------------------------------------------------------------------
# Parser unit test (dependency-free; validates the packed12 v5 wire decode
# against the firmware's packing reference).
# ------------------------------------------------------------------------------
if(BUILD_TESTING)
    add_executable(test_oglo_packet_parser
        tests/test_oglo_packet_parser.cpp
        oglo_packet_parser.cpp
    )
    target_include_directories(test_oglo_packet_parser PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME oglo_packet_parser COMMAND test_oglo_packet_parser)
endif()
