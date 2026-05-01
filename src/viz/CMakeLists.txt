# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20)

# ==============================================================================
# Televiz visualization module
# ==============================================================================
#
# Televiz mirrors the structure of src/core: a container of sub-modules, each
# with its own static library and (when needed) a sibling <module>_tests/
# directory.
#
# Sub-modules (planned):
#   core     — Vulkan + CUDA infrastructure, foundational types
#   layers   — LayerBase + concrete layer types (added with first layer)
#   session  — VizSession, VizCompositor, frame info (added with first session)
#   xr       — OpenXR backend (optional, BUILD_VIZ_XR)
#   python   — pybind11 module
#   shaders  — GLSL → SPIR-V at build time
# ==============================================================================

# Core: Vulkan/CUDA infrastructure and foundational types.
add_subdirectory(core)

# Layers: LayerBase abstract interface (header-only today; concrete layer
# types are added as they ship).
add_subdirectory(layers)

# Session: VizSession + VizCompositor + frame info — the orchestration
# layer that drives the per-frame loop and manages the layer registry.
add_subdirectory(session)

# Shaders: GLSL sources compiled to SPIR-V at build time and embedded
# as C arrays. Header-only INTERFACE library viz::shaders.
add_subdirectory(shaders)

# Python bindings (stub today; pybind11 module added later).
if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()

# Tests for each sub-module live in <module>_tests/ siblings.
if(BUILD_TESTING)
    add_subdirectory(core_tests)
    add_subdirectory(layers_tests)
    add_subdirectory(session_tests)
    add_subdirectory(shaders_tests)
endif()
