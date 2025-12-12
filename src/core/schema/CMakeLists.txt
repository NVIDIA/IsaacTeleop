# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

add_subdirectory(fbs)
add_subdirectory(cpp)

# ==============================================================================
# Python Bindings
# ==============================================================================
# Python bindings for schema types (optional, controlled by parent).

if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()
