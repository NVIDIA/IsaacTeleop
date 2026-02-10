# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(STATUS "Skipping generic_3axis_pedal plugin (Linux only)")
    add_custom_target(generic_3axis_pedal_plugin
        COMMAND ${CMAKE_COMMAND} -E echo "Skipping generic_3axis_pedal: Linux only")
    return()
endif()

add_executable(generic_3axis_pedal_plugin
    main.cpp
    generic_3axis_pedal_plugin.cpp
)

target_include_directories(generic_3axis_pedal_plugin PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

target_link_libraries(generic_3axis_pedal_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

install(TARGETS generic_3axis_pedal_plugin RUNTIME DESTINATION plugins/generic_3axis_pedal)
install(FILES plugin.yaml README.md DESTINATION plugins/generic_3axis_pedal)
