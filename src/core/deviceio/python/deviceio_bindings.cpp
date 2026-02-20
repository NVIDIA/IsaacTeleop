// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <deviceio/controller_tracker.hpp>
#include <deviceio/frame_metadata_tracker_oak.hpp>
#include <deviceio/full_body_tracker_pico.hpp>
#include <deviceio/hand_tracker.hpp>
#include <deviceio/head_tracker.hpp>
#include <deviceio_py_utils/session.hpp>
#include <openxr/openxr.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

PYBIND11_MODULE(_deviceio, m)
{
    m.doc() = "Isaac Teleop DeviceIO - Device I/O Module";

    // DeviceOutputTimestamp (FlatBuffer struct for tracker output timestamps)
    py::class_<core::DeviceOutputTimestamp>(m, "DeviceOutputTimestamp")
        .def_property_readonly("query_time_common_clock", &core::DeviceOutputTimestamp::query_time_common_clock)
        .def_property_readonly("target_time_common_clock", &core::DeviceOutputTimestamp::target_time_common_clock)
        .def_property_readonly("target_time_consumer_clock", &core::DeviceOutputTimestamp::target_time_consumer_clock)
        .def("__repr__",
             [](const core::DeviceOutputTimestamp& self)
             {
                 return "DeviceOutputTimestamp(query_time=" + std::to_string(self.query_time_common_clock()) +
                        ", target_time=" + std::to_string(self.target_time_common_clock()) +
                        ", target_time_consumer=" + std::to_string(self.target_time_consumer_clock()) + ")";
             });

    // TrackedT wrapper types (pair data + DeviceOutputTimestamp from each tracker)
    py::class_<core::HandPoseTrackedT>(m, "HandPoseTrackedT")
        .def_property_readonly(
            "data", [](const core::HandPoseTrackedT& self) -> const core::HandPoseT* { return self.data.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "timestamp",
            [](const core::HandPoseTrackedT& self) -> const core::DeviceOutputTimestamp* { return self.timestamp.get(); },
            py::return_value_policy::reference_internal);

    py::class_<core::HeadPoseTrackedT>(m, "HeadPoseTrackedT")
        .def_property_readonly(
            "data", [](const core::HeadPoseTrackedT& self) -> const core::HeadPoseT* { return self.data.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "timestamp",
            [](const core::HeadPoseTrackedT& self) -> const core::DeviceOutputTimestamp* { return self.timestamp.get(); },
            py::return_value_policy::reference_internal);

    py::class_<core::ControllerSnapshotTrackedT>(m, "ControllerSnapshotTrackedT")
        .def_property_readonly(
            "data",
            [](const core::ControllerSnapshotTrackedT& self) -> const core::ControllerSnapshot*
            { return self.data.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "timestamp",
            [](const core::ControllerSnapshotTrackedT& self) -> const core::DeviceOutputTimestamp*
            { return self.timestamp.get(); },
            py::return_value_policy::reference_internal);

    py::class_<core::FrameMetadataTrackedT>(m, "FrameMetadataTrackedT")
        .def_property_readonly(
            "data",
            [](const core::FrameMetadataTrackedT& self) -> const core::FrameMetadataT* { return self.data.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "timestamp",
            [](const core::FrameMetadataTrackedT& self) -> const core::DeviceOutputTimestamp*
            { return self.timestamp.get(); },
            py::return_value_policy::reference_internal);

    py::class_<core::FullBodyPosePicoTrackedT>(m, "FullBodyPosePicoTrackedT")
        .def_property_readonly(
            "data",
            [](const core::FullBodyPosePicoTrackedT& self) -> const core::FullBodyPosePicoT* { return self.data.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "timestamp",
            [](const core::FullBodyPosePicoTrackedT& self) -> const core::DeviceOutputTimestamp*
            { return self.timestamp.get(); },
            py::return_value_policy::reference_internal);

    // ITracker interface (base class)
    py::class_<core::ITracker, std::shared_ptr<core::ITracker>>(m, "ITracker").def("get_name", &core::ITracker::get_name);

    // HandTracker class
    py::class_<core::HandTracker, core::ITracker, std::shared_ptr<core::HandTracker>>(m, "HandTracker")
        .def(py::init<>())
        .def(
            "get_left_hand",
            [](core::HandTracker& self, PyDeviceIOSession& session) -> const core::HandPoseTrackedT&
            { return self.get_left_hand(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal)
        .def(
            "get_right_hand",
            [](core::HandTracker& self, PyDeviceIOSession& session) -> const core::HandPoseTrackedT&
            { return self.get_right_hand(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal)
        .def_static("get_joint_name", &core::HandTracker::get_joint_name);

    // HeadTracker class
    py::class_<core::HeadTracker, core::ITracker, std::shared_ptr<core::HeadTracker>>(m, "HeadTracker")
        .def(py::init<>())
        .def(
            "get_head",
            [](core::HeadTracker& self, PyDeviceIOSession& session) -> const core::HeadPoseTrackedT&
            { return self.get_head(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal);

    // ControllerTracker class
    py::class_<core::ControllerTracker, core::ITracker, std::shared_ptr<core::ControllerTracker>>(m, "ControllerTracker")
        .def(py::init<>())
        .def(
            "get_left_controller",
            [](core::ControllerTracker& self, PyDeviceIOSession& session) -> const core::ControllerSnapshotTrackedT&
            { return self.get_left_controller(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal, "Get the left controller tracked output")
        .def(
            "get_right_controller",
            [](core::ControllerTracker& self, PyDeviceIOSession& session) -> const core::ControllerSnapshotTrackedT&
            { return self.get_right_controller(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal, "Get the right controller tracked output");

    // FrameMetadataTrackerOak class
    py::class_<core::FrameMetadataTrackerOak, core::ITracker, std::shared_ptr<core::FrameMetadataTrackerOak>>(
        m, "FrameMetadataTrackerOak")
        .def(py::init<const std::string&, size_t>(), py::arg("collection_id"),
             py::arg("max_flatbuffer_size") = core::FrameMetadataTrackerOak::DEFAULT_MAX_FLATBUFFER_SIZE,
             "Construct a FrameMetadataTrackerOak for the given tensor collection ID")
        .def(
            "get_data",
            [](core::FrameMetadataTrackerOak& self, PyDeviceIOSession& session) -> const core::FrameMetadataTrackedT&
            { return self.get_data(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal,
            "Get the current frame metadata tracked output (data + timestamp)");

    // FullBodyTrackerPico class (PICO XR_BD_body_tracking extension)
    py::class_<core::FullBodyTrackerPico, core::ITracker, std::shared_ptr<core::FullBodyTrackerPico>>(
        m, "FullBodyTrackerPico")
        .def(py::init<>())
        .def(
            "get_body_pose",
            [](core::FullBodyTrackerPico& self, PyDeviceIOSession& session) -> const core::FullBodyPosePicoTrackedT&
            { return self.get_body_pose(session.native()); },
            py::arg("session"), py::return_value_policy::reference_internal,
            "Get full body pose tracked output (24 joints from pelvis to hands)");

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

    // Hand joint indices
    m.attr("JOINT_PALM") = static_cast<int>(XR_HAND_JOINT_PALM_EXT);
    m.attr("JOINT_WRIST") = static_cast<int>(XR_HAND_JOINT_WRIST_EXT);
    m.attr("JOINT_THUMB_TIP") = static_cast<int>(XR_HAND_JOINT_THUMB_TIP_EXT);
    m.attr("JOINT_INDEX_TIP") = static_cast<int>(XR_HAND_JOINT_INDEX_TIP_EXT);
}
