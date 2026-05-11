// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Bindings for the viz_core surface: enums, plain-data types
// (Resolution, Rect2D, Pose3D, Fov), VizBuffer, HostImage.

#include "bindings_helpers.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <viz/core/host_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/session/display_mode.hpp>
#include <viz/session/viz_session.hpp> // SessionState

#include <cstdint>
#include <memory>
#include <string>

namespace viz_py
{

namespace py = pybind11;
using namespace pybind11::literals;

void bind_core(py::module_& m)
{
    // ── Enums ──────────────────────────────────────────────────────────

    py::enum_<viz::DisplayMode>(m, "DisplayMode")
        .value("kOffscreen", viz::DisplayMode::kOffscreen)
        .value("kWindow", viz::DisplayMode::kWindow)
        .value("kXr", viz::DisplayMode::kXr);

    py::enum_<viz::PixelFormat>(m, "PixelFormat")
        .value("kRGBA8", viz::PixelFormat::kRGBA8)
        .value("kD32F", viz::PixelFormat::kD32F);

    py::enum_<viz::MemorySpace>(m, "MemorySpace")
        .value("kDevice", viz::MemorySpace::kDevice)
        .value("kHost", viz::MemorySpace::kHost);

    py::enum_<viz::SessionState>(m, "SessionState")
        .value("kUninitialized", viz::SessionState::kUninitialized)
        .value("kReady", viz::SessionState::kReady)
        .value("kRunning", viz::SessionState::kRunning)
        .value("kStopping", viz::SessionState::kStopping)
        .value("kLost", viz::SessionState::kLost)
        .value("kDestroyed", viz::SessionState::kDestroyed);

    // ── Plain-data types ───────────────────────────────────────────────

    py::class_<viz::Resolution>(m, "Resolution")
        .def(py::init<>())
        .def(py::init(
                 [](uint32_t w, uint32_t h) {
                     return viz::Resolution{ w, h };
                 }),
             "width"_a, "height"_a)
        .def_readwrite("width", &viz::Resolution::width)
        .def_readwrite("height", &viz::Resolution::height)
        .def("__repr__", [](const viz::Resolution& r)
             { return "Resolution(" + std::to_string(r.width) + ", " + std::to_string(r.height) + ")"; });

    py::class_<viz::Rect2D>(m, "Rect2D")
        .def(py::init<>())
        .def_readwrite("x", &viz::Rect2D::x)
        .def_readwrite("y", &viz::Rect2D::y)
        .def_readwrite("width", &viz::Rect2D::width)
        .def_readwrite("height", &viz::Rect2D::height);

    py::class_<viz::Pose3D>(m, "Pose3D",
                            R"doc(
3D pose in OpenXR stage space: right-handed, Y-up, meters.

position : (x, y, z) tuple of floats
orientation : (w, x, y, z) quaternion (identity = (1, 0, 0, 0))
)doc")
        .def(py::init<>())
        .def(py::init(
                 [](py::sequence position, py::sequence orientation)
                 {
                     if (py::len(position) != 3 || py::len(orientation) != 4)
                     {
                         throw std::runtime_error(
                             "Pose3D: position must be 3-sequence, orientation 4-sequence (w, x, y, z)");
                     }
                     viz::Pose3D p;
                     p.position =
                         glm::vec3(position[0].cast<float>(), position[1].cast<float>(), position[2].cast<float>());
                     p.orientation = glm::quat(orientation[0].cast<float>(), orientation[1].cast<float>(),
                                               orientation[2].cast<float>(), orientation[3].cast<float>());
                     return p;
                 }),
             "position"_a, "orientation"_a)
        .def_property(
            "position", [](const viz::Pose3D& p) { return py::make_tuple(p.position.x, p.position.y, p.position.z); },
            [](viz::Pose3D& p, py::sequence v)
            {
                if (py::len(v) != 3)
                    throw std::runtime_error("position must be a 3-sequence");
                p.position = glm::vec3(v[0].cast<float>(), v[1].cast<float>(), v[2].cast<float>());
            })
        .def_property(
            "orientation",
            [](const viz::Pose3D& p)
            { return py::make_tuple(p.orientation.w, p.orientation.x, p.orientation.y, p.orientation.z); },
            [](viz::Pose3D& p, py::sequence q)
            {
                if (py::len(q) != 4)
                    throw std::runtime_error("orientation must be a 4-sequence (w, x, y, z)");
                p.orientation = glm::quat(q[0].cast<float>(), q[1].cast<float>(), q[2].cast<float>(), q[3].cast<float>());
            });

    py::class_<viz::Fov>(m, "Fov")
        .def(py::init<>())
        .def_readwrite("angle_left", &viz::Fov::angle_left)
        .def_readwrite("angle_right", &viz::Fov::angle_right)
        .def_readwrite("angle_up", &viz::Fov::angle_up)
        .def_readwrite("angle_down", &viz::Fov::angle_down);

    // ── VizBuffer (with cuda/numpy interface) ──────────────────────────

    py::class_<viz::VizBuffer>(m, "VizBuffer",
                               R"doc(
Non-owning 2D pixel buffer descriptor.

Device buffers expose ``__cuda_array_interface__`` so CuPy / Numba /
PyTorch can wrap them zero-copy::

    arr = cupy.asarray(buf)

Host buffers expose ``__array_interface__`` for NumPy::

    arr = numpy.asarray(buf)
)doc")
        .def(py::init<>())
        .def_property(
            "data", [](const viz::VizBuffer& b) { return reinterpret_cast<uintptr_t>(b.data); },
            [](viz::VizBuffer& b, uintptr_t ptr) { b.data = reinterpret_cast<void*>(ptr); },
            "Raw data pointer as integer.")
        .def_readwrite("width", &viz::VizBuffer::width)
        .def_readwrite("height", &viz::VizBuffer::height)
        .def_readwrite("format", &viz::VizBuffer::format)
        .def_readwrite("pitch", &viz::VizBuffer::pitch)
        .def_readwrite("space", &viz::VizBuffer::space)
        .def_property_readonly(
            "__cuda_array_interface__",
            [](const viz::VizBuffer& b)
            {
                if (b.space != viz::MemorySpace::kDevice)
                {
                    throw py::attribute_error("__cuda_array_interface__ is only available for kDevice buffers");
                }
                // read_only=False: VizBuffer is a thin descriptor and
                // the producer owns the memory. PyTorch's CUDA path
                // hard-rejects read_only=True (numpy / cupy just take
                // it as a hint); writable is the permissive default.
                return make_array_interface(b, /*read_only=*/false);
            })
        .def_property_readonly(
            "__array_interface__",
            [](const viz::VizBuffer& b)
            {
                if (b.space != viz::MemorySpace::kHost)
                {
                    throw py::attribute_error("__array_interface__ is only available for kHost buffers");
                }
                return make_array_interface(b, /*read_only=*/false);
            });

    m.def("bytes_per_pixel", &viz::bytes_per_pixel, "format"_a, "Bytes per pixel for the given PixelFormat.");

    // ── HostImage ─────────────────────────────────────────────────────

    py::class_<viz::HostImage, std::shared_ptr<viz::HostImage>>(m, "HostImage",
                                                                R"doc(
Owning host-side pixel buffer. Returned by VizSession.readback_to_host().

Use ``numpy.asarray(img)`` for a zero-copy NumPy view that keeps the
HostImage alive while the array exists.
)doc")
        .def(py::init<>())
        .def(py::init<viz::Resolution, viz::PixelFormat>(), "resolution"_a, "format"_a)
        .def_property_readonly("resolution", &viz::HostImage::resolution)
        .def_property_readonly("format", &viz::HostImage::format)
        .def_property_readonly("size_bytes", &viz::HostImage::size_bytes)
        .def("view", static_cast<viz::VizBuffer (viz::HostImage::*)() noexcept>(&viz::HostImage::view),
             "Non-owning VizBuffer view (space=kHost) into the underlying storage.")
        .def_property_readonly("__array_interface__",
                               [](const viz::HostImage& img)
                               {
                                   if (img.data() == nullptr)
                                   {
                                       throw py::attribute_error("HostImage: storage is empty");
                                   }
                                   // numpy.asarray hands back a writable view of the
                                   // owned storage; the lifetime is bound to the
                                   // HostImage Python object's refcount.
                                   viz::VizBuffer v = const_cast<viz::HostImage&>(img).view();
                                   return make_array_interface(v, /*read_only=*/false);
                               });
}

} // namespace viz_py
