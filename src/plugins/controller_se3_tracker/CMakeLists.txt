# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(controller_se3_tracker_plugin
    main.cpp
    controller_se3_tracker_plugin.cpp
    controller_se3_tracker_plugin.hpp
)

target_link_libraries(controller_se3_tracker_plugin PRIVATE
    deviceio::deviceio_session
    deviceio::deviceio_trackers
    isaacteleop_schema
    oxr::oxr_core
    pusherio::pusherio
)

install(TARGETS controller_se3_tracker_plugin RUNTIME DESTINATION plugins/controller_se3_tracker)
install(FILES plugin.yaml README.md DESTINATION plugins/controller_se3_tracker)
