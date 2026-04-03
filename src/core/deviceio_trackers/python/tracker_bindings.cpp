// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <deviceio_trackers/controller_tracker.hpp>
#include <deviceio_trackers/frame_metadata_tracker_oak.hpp>
#include <deviceio_trackers/full_body_tracker_pico.hpp>
#include <deviceio_trackers/generic_3axis_pedal_tracker.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>
#include <schema/hand_generated.h>

namespace py = pybind11;

PYBIND11_MODULE(_deviceio_trackers, m)
{
    // Load schema pybind converters (TrackedT / schema types) before exposing tracker accessors.
    py::module_::import("isaacteleop.schema._schema");

    m.doc() = "Isaac Teleop DeviceIO - Tracker classes";

    py::class_<core::ITrackerSession>(m, "ITrackerSession");

    py::class_<core::ITracker, std::shared_ptr<core::ITracker>>(m, "ITracker").def("get_name", &core::ITracker::get_name);

    py::class_<core::HandTracker, core::ITracker, std::shared_ptr<core::HandTracker>>(m, "HandTracker")
        .def(py::init<>())
        .def(
            "get_left_hand",
            [](const core::HandTracker& self, const core::ITrackerSession& session) -> core::HandPoseTrackedT
            { return self.get_left_hand(session); },
            py::arg("session"))
        .def(
            "get_right_hand",
            [](const core::HandTracker& self, const core::ITrackerSession& session) -> core::HandPoseTrackedT
            { return self.get_right_hand(session); },
            py::arg("session"));

    py::class_<core::HeadTracker, core::ITracker, std::shared_ptr<core::HeadTracker>>(m, "HeadTracker")
        .def(py::init<>())
        .def(
            "get_head",
            [](const core::HeadTracker& self, const core::ITrackerSession& session) -> core::HeadPoseTrackedT
            { return self.get_head(session); },
            py::arg("session"));

    py::class_<core::ControllerTracker, core::ITracker, std::shared_ptr<core::ControllerTracker>>(m, "ControllerTracker")
        .def(py::init<>())
        .def(
            "get_left_controller",
            [](const core::ControllerTracker& self, const core::ITrackerSession& session) -> core::ControllerSnapshotTrackedT
            { return self.get_left_controller(session); },
            py::arg("session"), "Get the left controller tracked state (data is None if inactive)")
        .def(
            "get_right_controller",
            [](const core::ControllerTracker& self, const core::ITrackerSession& session) -> core::ControllerSnapshotTrackedT
            { return self.get_right_controller(session); },
            py::arg("session"), "Get the right controller tracked state (data is None if inactive)");

    py::class_<core::FrameMetadataTrackerOak, core::ITracker, std::shared_ptr<core::FrameMetadataTrackerOak>>(
        m, "FrameMetadataTrackerOak")
        .def(py::init<const std::string&, const std::vector<core::StreamType>&, size_t>(), py::arg("collection_prefix"),
             py::arg("streams"),
             py::arg("max_flatbuffer_size") = core::FrameMetadataTrackerOak::DEFAULT_MAX_FLATBUFFER_SIZE,
             "Construct a multi-stream FrameMetadataTrackerOak")
        .def(
            "get_stream_data",
            [](const core::FrameMetadataTrackerOak& self, const core::ITrackerSession& session,
               size_t stream_index) -> core::FrameMetadataOakTrackedT
            { return self.get_stream_data(session, stream_index); },
            py::arg("session"), py::arg("stream_index"),
            "Get FrameMetadataOakTrackedT for a specific stream by index; .data is None until first frame arrives")
        .def_property_readonly("stream_count", &core::FrameMetadataTrackerOak::get_stream_count,
                               "Number of streams this tracker is configured for");

    py::class_<core::Generic3AxisPedalTracker, core::ITracker, std::shared_ptr<core::Generic3AxisPedalTracker>>(
        m, "Generic3AxisPedalTracker")
        .def(py::init<const std::string&, size_t>(), py::arg("collection_id"),
             py::arg("max_flatbuffer_size") = core::Generic3AxisPedalTracker::DEFAULT_MAX_FLATBUFFER_SIZE,
             "Construct a Generic3AxisPedalTracker for the given tensor collection ID")
        .def(
            "get_pedal_data",
            [](const core::Generic3AxisPedalTracker& self,
               const core::ITrackerSession& session) -> core::Generic3AxisPedalOutputTrackedT
            { return self.get_data(session); },
            py::arg("session"), "Get the current foot pedal tracked state (data is None when no data available)");

    py::class_<core::FullBodyTrackerPico, core::ITracker, std::shared_ptr<core::FullBodyTrackerPico>>(
        m, "FullBodyTrackerPico")
        .def(py::init<>())
        .def(
            "get_body_pose",
            [](const core::FullBodyTrackerPico& self, const core::ITrackerSession& session) -> core::FullBodyPosePicoTrackedT
            { return self.get_body_pose(session); },
            py::arg("session"), "Get full body pose tracked state (data is None if inactive)");

    m.attr("NUM_JOINTS") = static_cast<int>(core::HandJoint_NUM_JOINTS);
    m.attr("JOINT_PALM") = static_cast<int>(core::HandJoint_PALM);
    m.attr("JOINT_WRIST") = static_cast<int>(core::HandJoint_WRIST);
    m.attr("JOINT_THUMB_TIP") = static_cast<int>(core::HandJoint_THUMB_TIP);
    m.attr("JOINT_INDEX_TIP") = static_cast<int>(core::HandJoint_INDEX_TIP);
}
