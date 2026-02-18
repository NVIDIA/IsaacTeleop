# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# Retargeting Engine UI - Pure Python Module
# ==============================================================================

# This module contains ImGui-based UI implementations for the retargeting engine.
# Requires optional dependencies (imgui, glfw).

cmake_minimum_required(VERSION 3.20)

# ==============================================================================
# Python Module
# ==============================================================================

if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()
