# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
    deviceio::deviceio_core
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
    deviceio::deviceio_core
    oxr::oxr_core
    teleopcore_schema
    ${CMAKE_DL_LIBS}
    Threads::Threads
)

# Install
install(TARGETS pedal_pusher pedal_printer
    RUNTIME DESTINATION examples/schemaio
)

install(FILES README.md
    DESTINATION examples/schemaio
)
