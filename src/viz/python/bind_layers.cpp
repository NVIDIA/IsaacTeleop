// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Bindings for viz_layers: QuadLayer + its config types. As
// ProjectionLayer / OverlayLayer ship, they bind here.
//
// Layers are owned by the session — Python handles are non-owning
// (py::nodelete). VizSession.add_quad_layer() is the only constructor;
// it lives in bind_session.cpp.

#include "bind_helpers.hpp"

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
        .def_readwrite("placement", &viz::QuadLayer::Config::placement);

    // ── QuadLayer (non-owning; session owns the lifetime) ─────────────

    py::class_<viz::QuadLayer, std::unique_ptr<viz::QuadLayer, py::nodelete>>(m, "QuadLayer",
                                                                              R"doc(
Single CUDA-fed quad layer. Owned by VizSession; the Python handle is
non-owning (don't keep it around past the session).

Call ``submit`` with a VizBuffer or any object exposing
``__cuda_array_interface__``. Render order = insertion order.
)doc")
        .def(
            "submit", [](viz::QuadLayer& self, const viz::VizBuffer& src) { self.submit(src); }, "src"_a,
            py::call_guard<py::gil_scoped_release>(), "Submit a pre-built VizBuffer (kDevice).")
        .def(
            "submit_cuda_array",
            [](viz::QuadLayer& self, py::object obj, uintptr_t stream)
            {
                // Accept anything exposing __cuda_array_interface__. Validate
                // the dict before constructing a VizBuffer — silent dtype /
                // shape / stride mismatches would surface inside the cudaMemcpy
                // as either corrupted pixels or a cryptic CUDA error.
                if (!py::hasattr(obj, "__cuda_array_interface__"))
                {
                    throw std::runtime_error("submit_cuda_array: object does not expose __cuda_array_interface__");
                }
                py::dict iface = obj.attr("__cuda_array_interface__").cast<py::dict>();
                if (!iface.contains("shape") || !iface.contains("typestr") || !iface.contains("data"))
                {
                    throw std::runtime_error(
                        "submit_cuda_array: __cuda_array_interface__ missing required key (shape/typestr/data)");
                }

                // Per-format expectations (typestr + channels). Must match the
                // layer's PixelFormat exactly — submit() reinterprets memory.
                const viz::PixelFormat fmt = self.format();
                const char* expected_typestr = nullptr;
                std::size_t expected_rank = 0;
                std::size_t expected_channels = 0;
                if (fmt == viz::PixelFormat::kRGBA8)
                {
                    expected_typestr = "|u1";
                    expected_rank = 3;
                    expected_channels = 4;
                }
                else if (fmt == viz::PixelFormat::kD32F)
                {
                    expected_typestr = "<f4";
                    expected_rank = 2;
                    expected_channels = 1;
                }
                else
                {
                    throw std::runtime_error("submit_cuda_array: unsupported layer PixelFormat");
                }

                const std::string typestr = iface["typestr"].cast<std::string>();
                if (typestr != expected_typestr)
                {
                    throw std::runtime_error(std::string("submit_cuda_array: typestr '") + typestr +
                                             "' does not match layer format (expected '" + expected_typestr + "')");
                }

                py::tuple shape = iface["shape"].cast<py::tuple>();
                if (shape.size() != expected_rank)
                {
                    throw std::runtime_error("submit_cuda_array: shape rank " + std::to_string(shape.size()) +
                                             " does not match layer format (expected " + std::to_string(expected_rank) +
                                             ")");
                }
                const uint32_t h = shape[0].cast<uint32_t>();
                const uint32_t w = shape[1].cast<uint32_t>();
                if (expected_channels > 1)
                {
                    const std::size_t c = shape[2].cast<std::size_t>();
                    if (c != expected_channels)
                    {
                        throw std::runtime_error("submit_cuda_array: channel count " + std::to_string(c) +
                                                 " does not match layer format (expected " +
                                                 std::to_string(expected_channels) + ")");
                    }
                }
                const viz::Resolution res = self.resolution();
                if (h != res.height || w != res.width)
                {
                    throw std::runtime_error("submit_cuda_array: shape (" + std::to_string(h) + ", " +
                                             std::to_string(w) + ") does not match layer resolution (" +
                                             std::to_string(res.height) + ", " + std::to_string(res.width) + ")");
                }

                // Row pitch: explicit if strides present + non-null (slice
                // views, padded buffers); else tightly packed.
                std::size_t pitch_bytes = 0;
                if (iface.contains("strides") && !iface["strides"].is_none())
                {
                    py::tuple strides = iface["strides"].cast<py::tuple>();
                    if (strides.size() != expected_rank)
                    {
                        throw std::runtime_error("submit_cuda_array: strides rank " + std::to_string(strides.size()) +
                                                 " does not match shape rank " + std::to_string(expected_rank));
                    }
                    pitch_bytes = strides[0].cast<std::size_t>();
                }

                py::tuple data = iface["data"].cast<py::tuple>();
                const uintptr_t ptr = data[0].cast<uintptr_t>();

                viz::VizBuffer buf;
                buf.data = reinterpret_cast<void*>(ptr);
                buf.width = w;
                buf.height = h;
                buf.format = fmt;
                buf.pitch = pitch_bytes; // 0 = tightly packed; submit() uses effective_pitch().
                buf.space = viz::MemorySpace::kDevice;
                py::gil_scoped_release release;
                self.submit(buf, reinterpret_cast<cudaStream_t>(stream));
            },
            "obj"_a, "stream"_a = 0, "Submit any object exposing __cuda_array_interface__ (CuPy / PyTorch / Numba).")
        .def_property_readonly("resolution", &viz::QuadLayer::resolution)
        .def_property_readonly("format", &viz::QuadLayer::format)
        .def_property_readonly("aspect_ratio", &viz::QuadLayer::aspect_ratio)
        .def("set_placement", &viz::QuadLayer::set_placement, "placement"_a,
             "Update placement at runtime. None switches to fullscreen (window mode only).")
        .def("placement", &viz::QuadLayer::placement)
        .def("set_visible", &viz::QuadLayer::set_visible, "visible"_a)
        .def("is_visible", &viz::QuadLayer::is_visible)
        .def_property_readonly("name", [](const viz::QuadLayer& l) { return l.name(); });
}

} // namespace viz_py
