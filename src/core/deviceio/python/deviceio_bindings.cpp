// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Prevent Windows.h from defining min/max macros that conflict with std::min/max
#if defined(_WIN32) || defined(_WIN64)
#    define NOMINMAX
#endif

#include <deviceio/controllertracker.hpp>
#include <deviceio/handtracker.hpp>
#include <deviceio/headtracker.hpp>
#include <deviceio_py/session.hpp>
#include <openxr/openxr.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

PYBIND11_MODULE(_deviceio, m)
{
    m.doc() = "TeleopCore DeviceIO - Device I/O Module";

    // ITracker interface (base class)
    py::class_<core::ITracker, std::shared_ptr<core::ITracker>>(m, "ITracker").def("get_name", &core::ITracker::get_name);

    // HandTracker class
    py::class_<core::HandTracker, core::ITracker, std::shared_ptr<core::HandTracker>>(m, "HandTracker")
        .def(py::init<>())
        .def(
            "get_left_hand",
            [](core::HandTracker& self, PyDeviceIOSession& session) -> const core::HandPoseT&
            { return self.get_left_hand(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal)
        .def(
            "get_right_hand",
            [](core::HandTracker& self, PyDeviceIOSession& session) -> const core::HandPoseT&
            { return self.get_right_hand(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal)
        .def_static("get_joint_name", &core::HandTracker::get_joint_name);

    // HeadTracker class
    py::class_<core::HeadTracker, core::ITracker, std::shared_ptr<core::HeadTracker>>(m, "HeadTracker")
        .def(py::init<>())
        .def(
            "get_head",
            [](core::HeadTracker& self, PyDeviceIOSession& session) -> const core::HeadPoseT&
            { return self.get_head(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal);

    // ControllerTracker class
    py::class_<core::ControllerTracker, core::ITracker, std::shared_ptr<core::ControllerTracker>>(m, "ControllerTracker")
        .def(py::init<>())
        .def(
            "get_controller_data",
            [](core::ControllerTracker& self, PyDeviceIOSession& session) -> const core::ControllerDataT&
            { return self.get_controller_data(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal,
            "Get complete controller data for both left and right controllers");

    // DeviceIOSession class (bound via wrapper for context management)
    // Other C++ modules (like mcap) should include <py_deviceio/session.hpp> and accept
    // PyDeviceIOSession& directly, calling .native() internally in C++ code.
    py::class_<PyDeviceIOSession>(m, "DeviceIOSession")
        .def("update", &PyDeviceIOSession::update, "Update session and all trackers")
        .def("__enter__", &PyDeviceIOSession::enter)
        .def("__exit__", &PyDeviceIOSession::exit)
        .def_static("get_required_extensions", &core::DeviceIOSession::get_required_extensions, py::arg("trackers"),
                    "Get list of OpenXR extensions required by a list of trackers")
        .def_static(
            "run",
            [](const std::vector<std::shared_ptr<core::ITracker>>& trackers, const core::OpenXRSessionHandles& handles)
            {
                // run() throws exceptions on failure, which pybind11 converts to Python exceptions
                auto session = core::DeviceIOSession::run(trackers, handles);
                // Wrap unique_ptr in PyDeviceIOSession, then unique_ptr for Python ownership
                return std::make_unique<PyDeviceIOSession>(std::move(session));
            },
            py::arg("trackers"), py::arg("handles"),
            "Create and initialize a session with trackers (returns context-managed session, throws on failure).");

    // Module constants - XR_HAND_JOINT_COUNT_EXT
    m.attr("NUM_JOINTS") = 26;

    // Joint indices
    m.attr("JOINT_PALM") = static_cast<int>(XR_HAND_JOINT_PALM_EXT);
    m.attr("JOINT_WRIST") = static_cast<int>(XR_HAND_JOINT_WRIST_EXT);
    m.attr("JOINT_THUMB_TIP") = static_cast<int>(XR_HAND_JOINT_THUMB_TIP_EXT);
    m.attr("JOINT_INDEX_TIP") = static_cast<int>(XR_HAND_JOINT_INDEX_TIP_EXT);
}
