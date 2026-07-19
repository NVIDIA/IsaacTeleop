# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

find_package(Threads REQUIRED)

# Create pusher executable
# Note: Examples link to oxr_core for OpenXR session creation, but pusherio itself doesn't
add_executable(pedal_pusher
    pedal_pusher.cpp
)

target_link_libraries(pedal_pusher PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Create pedal printer executable
add_executable(pedal_printer
    pedal_printer.cpp
)

target_link_libraries(pedal_printer PRIVATE
    deviceio::deviceio_session
        deviceio::deviceio_trackers
    oxr::oxr_core
    isaacteleop_schema
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Create SE3 tracker printer executable
add_executable(se3_printer
    se3_printer.cpp
)

target_link_libraries(se3_printer PRIVATE
    deviceio::deviceio_session
    deviceio::deviceio_trackers
    oxr::oxr_core
    isaacteleop_schema
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Create full body tracker printer executable
add_executable(full_body_printer
    full_body_printer.cpp
)

target_link_libraries(full_body_printer PRIVATE
    deviceio::deviceio_session
    deviceio::deviceio_trackers
    oxr::oxr_core
    isaacteleop_schema
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Create frame metadata printer executable
add_executable(frame_metadata_printer
    frame_metadata_printer.cpp
)

target_link_libraries(frame_metadata_printer PRIVATE
    deviceio::deviceio_session
        deviceio::deviceio_trackers
    oxr::oxr_core
    isaacteleop_schema
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Install
install(TARGETS pedal_pusher pedal_printer se3_printer full_body_printer frame_metadata_printer
    RUNTIME DESTINATION examples/schemaio
)
