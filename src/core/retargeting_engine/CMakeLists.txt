# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# Retargeting Engine - Pure Python Module
# ==============================================================================

# This module contains the type system for retargeting (no C++ bindings).

cmake_minimum_required(VERSION 3.20)

# ==============================================================================
# Python Module
# ==============================================================================

if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()