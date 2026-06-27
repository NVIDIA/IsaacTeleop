# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Adapted by X. Tian JP Tech. Initiatives Inc for Foottroller

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(STATUS "Skipping Foottroller plugin (Linux only)")
    add_custom_target(foottroller_plugin
        COMMAND ${CMAKE_COMMAND} -E echo "Skipping foottroller: Linux only")
    return()
endif()

add_executable(foottroller_plugin
    main.cpp
    foottroller_plugin.cpp
)

target_link_libraries(foottroller_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

install(TARGETS foottroller_plugin RUNTIME DESTINATION plugins/foottroller)
install(FILES plugin.yaml README.md DESTINATION plugins/foottroller)
