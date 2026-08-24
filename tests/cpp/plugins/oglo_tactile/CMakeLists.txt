# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Parser unit test (dependency-free; validates the packed12 v5 wire decode
# against the firmware's packing reference).
add_executable(test_oglo_packet_parser
    test_oglo_packet_parser.cpp
    ${CMAKE_SOURCE_DIR}/src/plugins/oglo_tactile/oglo_packet_parser.cpp
)
target_include_directories(test_oglo_packet_parser PRIVATE
    ${CMAKE_SOURCE_DIR}/src/plugins/oglo_tactile
)
add_test(NAME oglo_packet_parser COMMAND test_oglo_packet_parser)
