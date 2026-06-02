# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# FlatBuffer schemas are this module's language-neutral contract; each binding
# generates its own code from them.
set(SCHEMA_FBS_DIR ${CMAKE_CURRENT_SOURCE_DIR}/fbs)

add_subdirectory(cpp)

# ==============================================================================
# Python Bindings
# ==============================================================================
# Python bindings for schema types (optional, controlled by parent).

if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()
