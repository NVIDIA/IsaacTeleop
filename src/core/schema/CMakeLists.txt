# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# FlatBuffer schemas are this module's language-neutral contract; each binding
# generates its own code from them.
set(SCHEMA_FBS_DIR ${CMAKE_CURRENT_SOURCE_DIR}/fbs CACHE INTERNAL
    "Directory holding the FlatBuffer schemas")

# Binary schemas as of the last agreed revision. The conform test compares what the
# schemas compile to now against these; see README.md.
set(SCHEMA_GOLDEN_DIR ${CMAKE_CURRENT_SOURCE_DIR}/golden CACHE INTERNAL
    "Directory holding the checked-in golden .bfbs")

add_subdirectory(cpp)

# ==============================================================================
# Python Bindings
# ==============================================================================
# Python bindings for schema types (optional, controlled by parent).

if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()
