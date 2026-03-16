# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(STATUS "Skipping so101 plugin (Linux only)")
    add_custom_target(so101_arm_plugin
        COMMAND ${CMAKE_COMMAND} -E echo "Skipping so101: Linux only")
    return()
endif()

add_executable(so101_arm_plugin
    main.cpp
    so101_plugin.cpp
    feetech_driver.cpp
)

target_include_directories(so101_arm_plugin PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/inc
)

target_link_libraries(so101_arm_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

install(TARGETS so101_arm_plugin RUNTIME DESTINATION plugins/so101)
install(FILES plugin.yaml README.md DESTINATION plugins/so101)

# Build standalone tools
add_subdirectory(tools)
