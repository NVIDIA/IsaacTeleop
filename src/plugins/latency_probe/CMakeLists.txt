# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_executable(latency_probe_plugin
    main.cpp
    latency_probe_plugin.cpp
)

target_link_libraries(latency_probe_plugin PRIVATE
    deviceio::deviceio_session
    deviceio::deviceio_trackers
    isaacteleop_schema
    oxr::oxr_core
    pusherio::pusherio
)

install(TARGETS latency_probe_plugin RUNTIME DESTINATION plugins/latency_probe)
install(FILES plugin.yaml README.md DESTINATION plugins/latency_probe)
