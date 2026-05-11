// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// pybind11 entry point for the Televiz public surface.
//
// Module shape mirrors deviceio / oxr: a private extension module
// `_viz.so` lives next to the package `__init__.py`, which re-exports
// the symbols as `isaacteleop.viz`.
//
// The actual bindings are split along the C++ dep DAG (one
// <module>_bindings.cpp per sub-module). Registration order here must
// match the DAG:
// core → layers → session. Types referenced by signatures in later
// TUs (e.g. PixelFormat in QuadLayer::Config) need to be registered
// first or pybind11 fails at import time.
//
// Blocking calls (render, begin_frame, end_frame, submit, readback)
// release the GIL via py::call_guard so a Python frame-loop thread
// doesn't block other threads while waiting on Vulkan / NVDEC.

#include "bindings_helpers.hpp"

#include <pybind11/pybind11.h>

namespace py = pybind11;

PYBIND11_MODULE(_viz, m)
{
    m.doc() = "isaacteleop.viz — Televiz — Teleop Visualization API";

    viz_py::bind_core(m); // enums, plain types, VizBuffer, HostImage
    viz_py::bind_layers(m); // QuadLayer + Config + Placement (consumes core)
    viz_py::bind_session(m); // VizSession, FrameInfo (consumes core + layers)
}
