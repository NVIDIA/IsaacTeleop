# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(STATUS "Skipping spacemouse plugin (Linux only)")
    add_custom_target(spacemouse_plugin
        COMMAND ${CMAKE_COMMAND} -E echo "Skipping spacemouse: Linux only")
    return()
endif()

add_executable(spacemouse_plugin
    main.cpp
    spacemouse_plugin.cpp
)

target_link_libraries(spacemouse_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

install(TARGETS spacemouse_plugin RUNTIME DESTINATION plugins/spacemouse)
install(FILES plugin.yaml README.md DESTINATION plugins/spacemouse)
