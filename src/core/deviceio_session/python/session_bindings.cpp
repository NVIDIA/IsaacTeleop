// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <deviceio_py_utils/session.hpp>
#include <openxr/openxr.h>
#include <pybind11/stl.h>

#include <stdexcept>

namespace py = pybind11;

PYBIND11_MODULE(_deviceio_session, m)
{
    m.doc() = "Isaac Teleop DeviceIO - Session management";

    py::module_::import("isaacteleop.deviceio_trackers._deviceio_trackers");

    py::class_<core::PyDeviceIOSession, core::ITrackerSession, std::unique_ptr<core::PyDeviceIOSession>>(
        m, "DeviceIOSession")
        .def("update", &core::PyDeviceIOSession::update, "Update session and all trackers")
        .def("close", &core::PyDeviceIOSession::close,
             "Release the native session immediately (usually automatic via context manager)")
        .def("__enter__", &core::PyDeviceIOSession::enter)
        .def("__exit__", &core::PyDeviceIOSession::exit)
        .def_static("get_required_extensions", &core::DeviceIOSession::get_required_extensions, py::arg("trackers"),
                    "Get list of OpenXR extensions required by a list of trackers")
        .def_static(
            "run",
            [](const std::vector<std::shared_ptr<core::ITracker>>& trackers, const core::OpenXRSessionHandles& handles)
            {
                if (handles.instance == XR_NULL_HANDLE || handles.session == XR_NULL_HANDLE ||
                    handles.space == XR_NULL_HANDLE || handles.xrGetInstanceProcAddr == nullptr)
                {
                    throw std::runtime_error(
                        "DeviceIOSession.run: invalid OpenXRSessionHandles (instance, session, space must be non-null "
                        "handles and xrGetInstanceProcAddr must be set)");
                }
                auto session = core::DeviceIOSession::run(trackers, handles);
                return std::make_unique<core::PyDeviceIOSession>(std::move(session));
            },
            py::arg("trackers"), py::arg("handles"),
            "Create and initialize a session with trackers (returns context-managed session, throws on failure).");
}
