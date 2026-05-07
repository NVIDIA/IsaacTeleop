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
#   xr       — OpenXR backend (graphics-bound XR session)
#   python   — pybind11 module
#   shaders  — GLSL → SPIR-V at build time
# ==============================================================================

# Subdirectory order follows the dep DAG: a module's deps must be
# processed before it (CMake resolves alias targets at the link call).
#   core   ── foundational types, no deps
#   xr     ── depends on core
#   shaders── header-only, no deps (private dep of layers)
#   session── depends on core + xr; owns LayerBase (the layer contract)
#   layers ── concrete layer types; depends on core + session + shaders

# Core: Vulkan/CUDA infrastructure and foundational types.
add_subdirectory(core)

# XR: OpenXR-bound graphics session + XrBackend.
add_subdirectory(xr)

# Shaders: GLSL sources compiled to SPIR-V at build time and embedded
# as C arrays. Header-only INTERFACE library viz::shaders.
add_subdirectory(shaders)

# Session: VizSession + VizCompositor + LayerBase. Orchestration layer
# that drives the per-frame loop, manages the layer registry, and
# defines the contract concrete layers implement.
add_subdirectory(session)

# Layers: concrete layer types (QuadLayer, ...). Depends on session for
# the LayerBase abstract interface.
add_subdirectory(layers)

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
    add_subdirectory(xr_tests)
endif()
