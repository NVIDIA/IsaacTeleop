# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

find_package(Threads REQUIRED)

# Full body MCAP recorder example (C++ counterpart of record_full_body.py)
add_executable(record_full_body
    record_full_body.cpp
)

target_link_libraries(record_full_body PRIVATE
    deviceio::deviceio_session
    deviceio::deviceio_trackers
    oxr::oxr_core
    isaacteleop_schema
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Install
install(TARGETS record_full_body
    RUNTIME DESTINATION examples/mcap_record_replay/cpp
)
