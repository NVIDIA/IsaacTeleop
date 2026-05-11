// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// pybind11 bindings for the Televiz public surface.
//
// Module shape mirrors deviceio / oxr: a private extension module
// `_viz.so` lives next to the package `__init__.py`, which re-exports
// the symbols as `isaacteleop.viz`.
//
// Blocking calls (render, begin_frame, end_frame, submit, readback)
// release the GIL via py::call_guard so a Python frame-loop thread
// doesn't block other threads while waiting on Vulkan / NVDEC.

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <viz/core/host_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/display_mode.hpp>
#include <viz/session/frame_info.hpp>
#include <viz/session/viz_session.hpp>

#include <cstdint>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace py = pybind11;
using namespace pybind11::literals;

namespace
{

// ── Format helpers ──────────────────────────────────────────────────────

// `__cuda_array_interface__` / `__array_interface__` typestr per PixelFormat.
// kRGBA8 = 4 channels uint8, kD32F = 1 channel float32. Tightly-packed
// row major.
const char* typestr_for(viz::PixelFormat format)
{
    switch (format)
    {
    case viz::PixelFormat::kRGBA8:
        return "|u1";
    case viz::PixelFormat::kD32F:
        return "<f4";
    }
    throw std::runtime_error("VizBuffer: unknown PixelFormat");
}

// Shape tuple matching the typestr: (H, W, 4) for RGBA8, (H, W) for D32F.
py::tuple shape_for(uint32_t width, uint32_t height, viz::PixelFormat format)
{
    switch (format)
    {
    case viz::PixelFormat::kRGBA8:
        return py::make_tuple(height, width, 4);
    case viz::PixelFormat::kD32F:
        return py::make_tuple(height, width);
    }
    throw std::runtime_error("VizBuffer: unknown PixelFormat");
}

// Build the dict returned by __cuda_array_interface__ / __array_interface__.
// Version 3 of the protocol (matches what CuPy / Numba / PyTorch expect).
// `data` is (ptr_as_int, read_only). `strides` is None for C-contiguous,
// row-major; or an explicit tuple when the row pitch isn't tightly packed.
py::dict make_array_interface(const viz::VizBuffer& buf, bool read_only)
{
    if (buf.data == nullptr)
    {
        throw std::runtime_error("VizBuffer: data pointer is null — interface only valid for live buffers");
    }
    const size_t tight_pitch = static_cast<size_t>(buf.width) * viz::bytes_per_pixel(buf.format);
    const size_t row_pitch = buf.pitch != 0 ? buf.pitch : tight_pitch;
    py::object strides = py::none();
    if (row_pitch != tight_pitch)
    {
        // Explicit strides: (row, pixel[, channel]) in bytes. The channel
        // stride is the element size; the pixel stride is bytes-per-pixel;
        // the row stride is the (padded) pitch.
        const size_t bpp = viz::bytes_per_pixel(buf.format);
        if (buf.format == viz::PixelFormat::kRGBA8)
        {
            strides = py::make_tuple(row_pitch, bpp, static_cast<size_t>(1));
        }
        else
        {
            strides = py::make_tuple(row_pitch, bpp);
        }
    }
    py::dict d;
    d["shape"] = shape_for(buf.width, buf.height, buf.format);
    d["typestr"] = typestr_for(buf.format);
    d["data"] = py::make_tuple(reinterpret_cast<uintptr_t>(buf.data), read_only);
    d["strides"] = strides;
    d["version"] = 3;
    return d;
}

// ── HostImage view as numpy ────────────────────────────────────────────

// Wrap a HostImage's storage as a zero-copy numpy array. Lifetime: the
// array's `base` is set to the HostImage Python object so refcount keeps
// the storage alive while the array exists.
py::array host_image_to_numpy(viz::HostImage& img, py::object base)
{
    const auto res = img.resolution();
    const auto format = img.format();
    std::vector<py::ssize_t> shape;
    std::vector<py::ssize_t> strides;
    const py::ssize_t bpp = viz::bytes_per_pixel(format);
    if (format == viz::PixelFormat::kRGBA8)
    {
        shape = { res.height, res.width, 4 };
        strides = { static_cast<py::ssize_t>(res.width) * 4, 4, 1 };
        return py::array(py::dtype("uint8"), shape, strides, img.data(), base);
    }
    // kD32F
    shape = { res.height, res.width };
    strides = { static_cast<py::ssize_t>(res.width) * bpp, bpp };
    return py::array(py::dtype("float32"), shape, strides, img.data(), base);
}

} // namespace

PYBIND11_MODULE(_viz, m)
{
    m.doc() = "isaacteleop.viz — Televiz Vulkan compositor (C++ bindings)";

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

Both protocols return read-only views — the underlying memory is owned
by whatever produced the buffer (HostImage, QuadLayer slot, external
producer).
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
                                   // Use the const view but flag read_only=false
                                   // — numpy.asarray hands back a writable view.
                                   viz::VizBuffer v = const_cast<viz::HostImage&>(img).view();
                                   return make_array_interface(v, /*read_only=*/false);
                               });

    // ── FrameInfo + timing ─────────────────────────────────────────────

    py::class_<viz::FrameInfo>(m, "FrameInfo")
        .def(py::init<>())
        .def_readonly("frame_index", &viz::FrameInfo::frame_index)
        .def_readonly("predicted_display_time", &viz::FrameInfo::predicted_display_time)
        .def_readonly("delta_time", &viz::FrameInfo::delta_time)
        .def_readonly("should_render", &viz::FrameInfo::should_render)
        .def_readonly("resolution", &viz::FrameInfo::resolution);

    py::class_<viz::FrameTimingStats>(m, "FrameTimingStats")
        .def(py::init<>())
        .def_readonly("render_fps", &viz::FrameTimingStats::render_fps)
        .def_readonly("target_fps", &viz::FrameTimingStats::target_fps)
        .def_readonly("missed_frames", &viz::FrameTimingStats::missed_frames)
        .def_readonly("avg_frame_time_ms", &viz::FrameTimingStats::avg_frame_time_ms)
        .def_readonly("gpu_time_ms", &viz::FrameTimingStats::gpu_time_ms)
        .def_readonly("stale_layers", &viz::FrameTimingStats::stale_layers);

    py::class_<viz::VizCompositor::GpuFrameTiming>(m, "GpuFrameTiming")
        .def(py::init<>())
        .def_readonly("total_ms", &viz::VizCompositor::GpuFrameTiming::total_ms)
        .def_readonly("render_pass_ms", &viz::VizCompositor::GpuFrameTiming::render_pass_ms)
        .def_readonly("post_pass_ms", &viz::VizCompositor::GpuFrameTiming::post_pass_ms);

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
                // Accept anything that exposes __cuda_array_interface__.
                // Constructs a VizBuffer on the fly from the interface
                // dict's data pointer + shape, then forwards to the
                // C++ submit(). Stream is optional (0 = default stream).
                if (!py::hasattr(obj, "__cuda_array_interface__"))
                {
                    throw std::runtime_error("submit_cuda_array: object does not expose __cuda_array_interface__");
                }
                py::dict iface = obj.attr("__cuda_array_interface__").cast<py::dict>();
                py::tuple shape = iface["shape"].cast<py::tuple>();
                if (shape.size() < 2)
                {
                    throw std::runtime_error("submit_cuda_array: array must have at least 2 dimensions (H, W[, C])");
                }
                py::tuple data = iface["data"].cast<py::tuple>();
                const uintptr_t ptr = data[0].cast<uintptr_t>();
                viz::VizBuffer buf;
                buf.data = reinterpret_cast<void*>(ptr);
                buf.height = shape[0].cast<uint32_t>();
                buf.width = shape[1].cast<uint32_t>();
                buf.format = self.format();
                buf.pitch = 0; // Assume tightly packed; caller should set if not.
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

    // ── VizSession::Config ────────────────────────────────────────────

    py::class_<viz::VizSession::Config>(m, "VizSessionConfig")
        .def(py::init<>())
        .def_readwrite("mode", &viz::VizSession::Config::mode)
        .def_readwrite("window_width", &viz::VizSession::Config::window_width)
        .def_readwrite("window_height", &viz::VizSession::Config::window_height)
        .def_readwrite("app_name", &viz::VizSession::Config::app_name)
        .def_readwrite("xr_system_wait_seconds", &viz::VizSession::Config::xr_system_wait_seconds)
        .def_readwrite("xr_near_z", &viz::VizSession::Config::xr_near_z)
        .def_readwrite("xr_far_z", &viz::VizSession::Config::xr_far_z)
        .def_readwrite("gpu_timing", &viz::VizSession::Config::gpu_timing)
        .def_property(
            "clear_color",
            [](const viz::VizSession::Config& c)
            { return py::make_tuple(c.clear_color[0], c.clear_color[1], c.clear_color[2], c.clear_color[3]); },
            [](viz::VizSession::Config& c, py::sequence rgba)
            {
                if (py::len(rgba) != 4)
                    throw std::runtime_error("clear_color must be a 4-sequence (r, g, b, a)");
                for (int i = 0; i < 4; ++i)
                    c.clear_color[i] = rgba[i].cast<float>();
            },
            "Initial clear color (RGBA in [0, 1]).");

    // ── VizSession ────────────────────────────────────────────────────

    py::class_<viz::VizSession>(m, "VizSession",
                                R"doc(
Top-level Televiz session. Owns the Vulkan context, compositor, and
layer registry.

Construct via ``VizSession.create(config)``. Add layers with
``add_quad_layer(config)``. Drive the frame loop with ``render()``
(one-shot) or ``begin_frame()`` / ``end_frame()`` (paired).
)doc")
        .def_static("create", &viz::VizSession::create, "config"_a,
                    "Factory: validates config + initializes Vulkan / display backend.")
        .def("destroy", &viz::VizSession::destroy, py::call_guard<py::gil_scoped_release>())
        .def(
            "add_quad_layer",
            [](viz::VizSession& self, viz::QuadLayer::Config config) -> viz::QuadLayer*
            {
                const auto* ctx = self.get_vk_context();
                const auto render_pass = self.get_render_pass();
                if (ctx == nullptr || render_pass == VK_NULL_HANDLE)
                {
                    throw std::runtime_error("VizSession: cannot add layer before session is initialized");
                }
                return self.add_layer<viz::QuadLayer>(*ctx, render_pass, std::move(config));
            },
            "config"_a, py::return_value_policy::reference_internal,
            "Construct + register a QuadLayer. Returns a non-owning handle.")
        .def("render", &viz::VizSession::render, py::call_guard<py::gil_scoped_release>(),
             "Wait + composite + present in one call. Returns FrameInfo.")
        .def("begin_frame", &viz::VizSession::begin_frame, py::call_guard<py::gil_scoped_release>())
        .def("end_frame", &viz::VizSession::end_frame, py::call_guard<py::gil_scoped_release>())
        .def("get_state", &viz::VizSession::get_state)
        .def("get_recommended_resolution", &viz::VizSession::get_recommended_resolution)
        .def("get_frame_timing_stats", &viz::VizSession::get_frame_timing_stats)
        .def("get_gpu_timing", &viz::VizSession::get_gpu_timing)
        .def("readback_to_host", &viz::VizSession::readback_to_host, py::call_guard<py::gil_scoped_release>(),
             "Most-recent frame as RGBA8 host pixels. kOffscreen only.")
        .def("should_close", &viz::VizSession::should_close)
        .def("is_xr_mode", &viz::VizSession::is_xr_mode)
        .def("has_xr_time_conversion", &viz::VizSession::has_xr_time_conversion)
        .def("head_pose_now", &viz::VizSession::head_pose_now,
             "Current head pose (kXr only). None on tracking loss or missing time-conversion ext.")
        // Raw handle accessors as integers — for callers wiring Televiz into
        // a foreign Vulkan / OpenXR app. Most users won't touch these.
        .def_property_readonly(
            "vk_device", [](const viz::VizSession& s) { return reinterpret_cast<uintptr_t>(s.get_vk_device()); })
        .def_property_readonly("vk_physical_device", [](const viz::VizSession& s)
                               { return reinterpret_cast<uintptr_t>(s.get_vk_physical_device()); })
        .def_property_readonly("vk_queue_family_index", &viz::VizSession::get_vk_queue_family_index);
}
