// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <deviceio_py_utils/session.hpp>
#include <deviceio_session/deviceio_session.hpp>
#include <openxr/openxr.h>
#include <pybind11/stl.h>

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
                                          "MCAP configuration for live recording and replay sessions. "
                                          "Pass to run() to enable recording, "
                                          "or to replay() to read back recorded data.")
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
        .def("update", &core::PyDeviceIOSession::update, "Update session and all trackers")
        .def("close", &core::PyDeviceIOSession::close,
             "Release the native session immediately (usually automatic via context manager)")
        .def("__enter__", &core::PyDeviceIOSession::enter)
        .def("__exit__", &core::PyDeviceIOSession::exit)
        .def_static("get_required_extensions", &core::DeviceIOSession::get_required_extensions, py::arg("trackers"),
                    "Aggregate OpenXR extensions required for a live session with these tracker types "
                    "(not a per-tracker instance method)")
        .def_static(
            "run",
            [](const std::vector<std::shared_ptr<core::ITracker>>& trackers, const core::OpenXRSessionHandles& handles,
               std::optional<core::McapRecordingConfig> mcap_config)
            {
                if (handles.instance == XR_NULL_HANDLE || handles.session == XR_NULL_HANDLE ||
                    handles.space == XR_NULL_HANDLE || handles.xrGetInstanceProcAddr == nullptr)
                {
                    throw std::runtime_error(
                        "DeviceIOSession.run: invalid OpenXRSessionHandles (instance, session, space "
                        "must be non-null handles and xrGetInstanceProcAddr must be set)");
                }
                auto session = core::DeviceIOSession::run(trackers, handles, std::move(mcap_config));
                return std::make_unique<core::PyDeviceIOSession>(std::move(session));
            },
            py::arg("trackers"), py::arg("handles"), py::arg("mcap_config") = py::none(),
            "Create and initialize a live OpenXR session with trackers. "
            "Pass a McapRecordingConfig to enable MCAP recording.")
        .def_static(
            "replay",
            [](const core::McapRecordingConfig& mcap_config)
            {
                auto session = core::DeviceIOSession::replay(mcap_config);
                return std::make_unique<core::PyDeviceIOSession>(std::move(session));
            },
            py::arg("mcap_config"),
            "Create a replay session that reads recorded data from an MCAP file. "
            "The McapRecordingConfig.tracker_names maps tracker objects to their MCAP channel base names.");
}
