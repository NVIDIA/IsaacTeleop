# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(external_skeleton_plugin
    main.cpp
    external_skeleton_plugin.cpp
    synthetic_skeleton_source.cpp
)

target_include_directories(external_skeleton_plugin PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

target_link_libraries(external_skeleton_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

install(TARGETS external_skeleton_plugin RUNTIME DESTINATION plugins/external_skeleton)
install(FILES plugin.yaml README.md DESTINATION plugins/external_skeleton)
