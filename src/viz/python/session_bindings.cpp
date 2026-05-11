// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Bindings for viz_session: FrameInfo, FrameTimingStats, GpuFrameTiming,
// VizSessionConfig, VizSession. VizSession owns layers — add_quad_layer
// here returns a non-owning handle whose py::class_ is registered in
// layers_bindings.cpp, so bind_layers(m) must run before bind_session(m)
// in PYBIND11_MODULE.

#include "bindings_helpers.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/frame_info.hpp>
#include <viz/session/viz_session.hpp>

#include <cstdint>
#include <stdexcept>

namespace viz_py
{

namespace py = pybind11;
using namespace pybind11::literals;

void bind_session(py::module_& m)
{
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

} // namespace viz_py
