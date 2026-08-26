# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# Handle all project dependencies
add_subdirectory(third_party)

if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(v2d)
endif()
