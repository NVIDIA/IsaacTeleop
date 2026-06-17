// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Bindings for viz_layers: QuadLayer + its config types. As
// ProjectionLayer / OverlayLayer ship, they bind here.
//
// Layers are owned by the session — Python handles are non-owning
// (py::nodelete). VizSession.add_quad_layer() is the only constructor;
// it lives in session_bindings.cpp.

#include "bindings_helpers.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <viz/core/viz_buffer.hpp>
#include <viz/layers/quad_layer.hpp>

#include <cstdint>
#include <memory>

namespace viz_py
{

namespace py = pybind11;
using namespace pybind11::literals;

void bind_layers(py::module_& m)
{
    // ── QuadLayer::Config + Placement ──────────────────────────────────

    py::class_<viz::QuadLayer::Config::Placement>(m, "QuadLayerPlacement")
        .def(py::init<>())
        .def(py::init(
                 [](viz::Pose3D pose, py::sequence size_meters)
                 {
                     if (py::len(size_meters) != 2)
                         throw std::runtime_error("size_meters must be a 2-sequence (w, h)");
                     viz::QuadLayer::Config::Placement p;
                     p.pose = pose;
                     p.size_meters = glm::vec2(size_meters[0].cast<float>(), size_meters[1].cast<float>());
                     return p;
                 }),
             "pose"_a, "size_meters"_a)
        .def_readwrite("pose", &viz::QuadLayer::Config::Placement::pose)
        .def_property(
            "size_meters",
            [](const viz::QuadLayer::Config::Placement& p) { return py::make_tuple(p.size_meters.x, p.size_meters.y); },
            [](viz::QuadLayer::Config::Placement& p, py::sequence s)
            {
                if (py::len(s) != 2)
                    throw std::runtime_error("size_meters must be a 2-sequence (w, h)");
                p.size_meters = glm::vec2(s[0].cast<float>(), s[1].cast<float>());
            });

    py::class_<viz::QuadLayer::Config>(m, "QuadLayerConfig")
        .def(py::init<>())
        .def_readwrite("name", &viz::QuadLayer::Config::name)
        .def_readwrite("resolution", &viz::QuadLayer::Config::resolution)
        .def_readwrite("format", &viz::QuadLayer::Config::format)
        .def_readwrite("placement", &viz::QuadLayer::Config::placement)
        .def_readwrite("generate_mipmaps", &viz::QuadLayer::Config::generate_mipmaps,
                       "Allocate + regenerate a capped mip chain each frame; sampler "
                       "uses trilinear filtering. On by default.")
        .def_readwrite("stereo", &viz::QuadLayer::Config::stereo,
                       "Per-eye stereo. When true, submit MUST be called with both buffers; "
                       "view 0 (left eye) samples the left buffer, view 1 (right eye) the right. "
                       "Memory doubles. Off by default.")
        .def_readwrite("stereo_baseline_mm", &viz::QuadLayer::Config::stereo_baseline_mm,
                       "Horizontal disparity between left and right planes (millimeters), "
                       "applied along the placement's local +x axis. 0 → both eyes see the "
                       "same world quad. Ignored unless stereo + kXr. mm-scale chosen because "
                       "typical IPDs / stereo camera baselines are 50–80 mm.");

    // ── QuadLayer (non-owning; session owns the lifetime) ─────────────

    py::class_<viz::QuadLayer, std::unique_ptr<viz::QuadLayer, py::nodelete>>(m, "QuadLayer",
                                                                              R"doc(
Single CUDA-fed quad layer. Owned by VizSession; the Python handle is
non-owning (don't keep it around past the session).

Render order = insertion order. Call ``submit(left, right=None, stream=0)``:

  * Mono layer (Config.stereo == False): pass exactly one buffer as
    ``left``. Passing ``right`` raises ``RuntimeError``.
  * Stereo layer (Config.stereo == True): pass both. Missing ``right``
    raises ``RuntimeError``. Both buffers are copied on the same CUDA
    stream + a single semaphore signals when they're both ready, so
    the renderer never sees a half-matched pair.

Each buffer is either a ``VizBuffer`` (passed straight to C++) or any
object exposing ``__cuda_array_interface__`` (CuPy / PyTorch / Numba /
numpy on a CUDA device pointer); the binding converts it on the fly.
)doc")
        .def(
            "submit",
            [](viz::QuadLayer& self, py::object left, py::object right, uintptr_t stream)
            {
                // Resolve each Python arg to a VizBuffer. VizBuffer passes
                // through; anything else goes via the cuda-array-interface
                // converter (which validates dtype / shape / strides
                // before constructing the buffer).
                auto to_buf = [&self](py::object obj, const char* label) -> viz::VizBuffer
                {
                    if (py::isinstance<viz::VizBuffer>(obj))
                    {
                        return obj.cast<viz::VizBuffer>();
                    }
                    return cuda_array_to_viz_buffer(obj, self.format(), self.resolution(), label);
                };

                if (right.is_none())
                {
                    viz::VizBuffer left_buf = to_buf(left, "QuadLayer.submit(left)");
                    py::gil_scoped_release release;
                    self.submit(left_buf, reinterpret_cast<cudaStream_t>(stream));
                }
                else
                {
                    viz::VizBuffer left_buf = to_buf(left, "QuadLayer.submit(left)");
                    viz::VizBuffer right_buf = to_buf(right, "QuadLayer.submit(right)");
                    py::gil_scoped_release release;
                    self.submit(left_buf, right_buf, reinterpret_cast<cudaStream_t>(stream));
                }
            },
            "left"_a, "right"_a = py::none(), "stream"_a = 0,
            "Submit a frame. Each arg is a VizBuffer or any __cuda_array_interface__ "
            "object. Mono layer: pass only ``left``. Stereo layer: pass both.")
        .def_property_readonly("resolution", &viz::QuadLayer::resolution)
        .def_property_readonly("format", &viz::QuadLayer::format)
        .def_property_readonly("aspect_ratio", &viz::QuadLayer::aspect_ratio)
        .def("set_placement", &viz::QuadLayer::set_placement, "placement"_a,
             "Update placement at runtime. None switches to fullscreen (window mode only).")
        .def("placement", &viz::QuadLayer::placement)
        // LayerBase itself is not exposed to Python, so bind inherited
        // visibility helpers through lambdas on QuadLayer. Binding the
        // raw LayerBase member pointer here makes pybind11 expect a
        // registered LayerBase Python instance as ``self``.
        .def(
            "set_visible", [](viz::QuadLayer& self, bool visible) { self.set_visible(visible); }, "visible"_a)
        .def("is_visible", [](const viz::QuadLayer& self) { return self.is_visible(); })
        .def_property_readonly("name", [](const viz::QuadLayer& l) { return l.name(); });
}

} // namespace viz_py
