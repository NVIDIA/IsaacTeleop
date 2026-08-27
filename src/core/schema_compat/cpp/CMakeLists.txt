# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Grades one FlatBuffers binary schema against another: whether data written under the
# first still reads under the second.
add_library(schema_compat STATIC
    schema_compat.cpp
    inc/schema_compat/schema_compat.hpp
)

target_include_directories(schema_compat
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

target_link_libraries(schema_compat
    PRIVATE
        flatbuffers
)

add_library(schema::schema_compat ALIAS schema_compat)
