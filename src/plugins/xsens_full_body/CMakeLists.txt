# SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(STATUS "Skipping xsens_full_body plugin (Linux only)")
    add_custom_target(xsens_full_body_plugin
        COMMAND ${CMAKE_COMMAND} -E echo "Skipping xsens_full_body: Linux only")
    return()
endif()

# No vendor SDK: MVN Studio performs the skeleton conversion itself and emits the schema this
# repo already defines, so the plugin needs nothing beyond the core libraries.
add_executable(xsens_full_body_plugin
    main.cpp
    xsens_full_body_plugin.cpp
    frame_decision.cpp
    plugin_options.cpp
)

target_link_libraries(xsens_full_body_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

install(TARGETS xsens_full_body_plugin RUNTIME DESTINATION plugins/xsens_full_body)
install(FILES plugin.yaml README.md DESTINATION plugins/xsens_full_body)

# Unit tests for the two pieces the plugin can be taken apart into: what it decides about a
# datagram, and what it decides about a command line. Both link their unit directly and need no
# OpenXR runtime, so they run anywhere.
if(BUILD_TESTING)
    add_executable(test_xsens_frame_decision
        tests/test_frame_decision.cpp
        frame_decision.cpp
    )
    target_include_directories(test_xsens_frame_decision PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_link_libraries(test_xsens_frame_decision PRIVATE isaacteleop_schema)
    add_test(NAME xsens_frame_decision COMMAND test_xsens_frame_decision)

    # Lighter still than the above: argument parsing pulls in neither flatbuffers nor the schema.
    add_executable(test_xsens_plugin_options
        tests/test_plugin_options.cpp
        plugin_options.cpp
    )
    target_include_directories(test_xsens_plugin_options PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME xsens_plugin_options COMMAND test_xsens_plugin_options)
endif()
