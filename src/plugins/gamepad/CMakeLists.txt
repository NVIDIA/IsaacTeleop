# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(STATUS "Skipping gamepad plugin (Linux only)")
    add_custom_target(gamepad_plugin
        COMMAND ${CMAKE_COMMAND} -E echo "Skipping gamepad: Linux only")
    return()
endif()

add_executable(gamepad_plugin
    main.cpp
    gamepad_plugin.cpp
)

target_link_libraries(gamepad_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

install(TARGETS gamepad_plugin RUNTIME DESTINATION plugins/gamepad)
install(FILES plugin.yaml README.md DESTINATION plugins/gamepad)
