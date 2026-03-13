// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <deviceio_py_utils/session.hpp>
#include <deviceio_session/deviceio_session.hpp>
#include <openxr/openxr.h>
#include <pybind11/stl.h>
#include <time_utils/os_time.hpp>

#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace py = pybind11;

PYBIND11_MODULE(_deviceio_session, m)
{
    m.doc() = "Isaac Teleop DeviceIO - Session management";

    py::module_::import("isaacteleop.deviceio_trackers._deviceio_trackers");

    py::class_<core::McapRecordingConfig>(m, "McapRecordingConfig",
                                          "Configuration for MCAP recording. "
                                          "Pass to DeviceIOSession.run() to enable recording, "
                                          "or omit / pass None to disable.")
        .def(py::init(
                 [](const std::string& filename,
                    const std::vector<std::pair<std::shared_ptr<core::ITracker>, std::string>>& tracker_names)
                 {
                     core::McapRecordingConfig config;
                     config.filename = filename;
                     for (const auto& [tracker, name] : tracker_names)
                     {
                         config.tracker_names.emplace_back(tracker.get(), name);
                     }
                     return config;
                 }),
             py::arg("filename"), py::arg("tracker_names"))
        .def_readwrite("filename", &core::McapRecordingConfig::filename);

    py::class_<core::PyDeviceIOSession, core::ITrackerSession, std::unique_ptr<core::PyDeviceIOSession>>(
        m, "DeviceIOSession")
        .def(
            "update",
            [](core::PyDeviceIOSession& self, std::optional<int64_t> target_monotonic_time_ns)
            {
                int64_t t = target_monotonic_time_ns ? *target_monotonic_time_ns : core::os_monotonic_now_ns();
                return self.update(t);
            },
            py::arg("target_monotonic_time_ns") = py::none(),
            "Update session and all trackers. "
            "If target_monotonic_time_ns is omitted, the current system monotonic time is used.")
        .def("close", &core::PyDeviceIOSession::close,
             "Release the native session immediately (usually automatic via context manager)")
        .def("__enter__", &core::PyDeviceIOSession::enter)
        .def("__exit__", &core::PyDeviceIOSession::exit)
        .def_static("get_required_extensions", &core::DeviceIOSession::get_required_extensions, py::arg("trackers"),
                    "Get list of OpenXR extensions required by a list of trackers")
        .def_static(
            "run",
            [](const std::vector<std::shared_ptr<core::ITracker>>& trackers, const core::OpenXRSessionHandles& handles,
               std::optional<core::McapRecordingConfig> recording_config)
            {
                if (handles.instance == XR_NULL_HANDLE || handles.session == XR_NULL_HANDLE ||
                    handles.space == XR_NULL_HANDLE || handles.xrGetInstanceProcAddr == nullptr)
                {
                    throw std::runtime_error(
                        "DeviceIOSession.run: invalid OpenXRSessionHandles (instance, session, space must be non-null "
                        "handles and xrGetInstanceProcAddr must be set)");
                }
                auto session = core::DeviceIOSession::run(trackers, handles, std::move(recording_config));
                return std::make_unique<core::PyDeviceIOSession>(std::move(session));
            },
            py::arg("trackers"), py::arg("handles"), py::arg("recording_config") = py::none(),
            "Create and initialize a session with trackers. "
            "Pass a McapRecordingConfig to enable MCAP recording.");
}
