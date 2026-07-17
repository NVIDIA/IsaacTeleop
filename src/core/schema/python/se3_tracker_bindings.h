// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Se3TrackerPose FlatBuffer schema.
// Se3TrackerPoseT is a table type (mutable object-API) with pose and is_valid fields.

#pragma once

#include <pybind11/pybind11.h>
#include <schema/se3_tracker_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_se3_tracker(py::module& m)
{
    // Bind Se3TrackerPoseT class (FlatBuffers object API for tables).
    py::class_<Se3TrackerPoseT, std::shared_ptr<Se3TrackerPoseT>>(m, "Se3TrackerPoseT")
        .def(py::init(
            []()
            {
                auto obj = std::make_shared<Se3TrackerPoseT>();
                obj->pose = std::make_shared<Pose>();
                return obj;
            }))
        .def(py::init(
                 [](const Pose& pose, bool is_valid)
                 {
                     auto obj = std::make_shared<Se3TrackerPoseT>();
                     obj->pose = std::make_shared<Pose>(pose);
                     obj->is_valid = is_valid;
                     return obj;
                 }),
             py::arg("pose"), py::arg("is_valid"))
        .def_property_readonly(
            "pose", [](const Se3TrackerPoseT& self) -> const Pose* { return self.pose.get(); },
            py::return_value_policy::reference_internal)
        .def_readonly("is_valid", &Se3TrackerPoseT::is_valid)
        .def("__repr__",
             [](const Se3TrackerPoseT& self)
             {
                 std::string pose_str = "None";
                 if (self.pose)
                 {
                     pose_str = "Pose(position=Point(x=" + std::to_string(self.pose->position().x()) +
                                ", y=" + std::to_string(self.pose->position().y()) +
                                ", z=" + std::to_string(self.pose->position().z()) +
                                "), orientation=Quaternion(x=" + std::to_string(self.pose->orientation().x()) +
                                ", y=" + std::to_string(self.pose->orientation().y()) +
                                ", z=" + std::to_string(self.pose->orientation().z()) +
                                ", w=" + std::to_string(self.pose->orientation().w()) + "))";
                 }
                 return "Se3TrackerPoseT(pose=" + pose_str + ", is_valid=" + (self.is_valid ? "True" : "False") + ")";
             });

    py::class_<Se3TrackerPoseRecordT, std::shared_ptr<Se3TrackerPoseRecordT>>(m, "Se3TrackerPoseRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const Se3TrackerPoseT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<Se3TrackerPoseRecordT>();
                     obj->data = std::make_shared<Se3TrackerPoseT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly(
            "data", [](const Se3TrackerPoseRecordT& self) -> std::shared_ptr<Se3TrackerPoseT> { return self.data; })
        .def_readonly("timestamp", &Se3TrackerPoseRecordT::timestamp)
        .def("__repr__", [](const Se3TrackerPoseRecordT& self)
             { return "Se3TrackerPoseRecord(data=" + std::string(self.data ? "Se3TrackerPoseT(...)" : "None") + ")"; });

    py::class_<Se3TrackerPoseTrackedT, std::shared_ptr<Se3TrackerPoseTrackedT>>(m, "Se3TrackerPoseTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const Se3TrackerPoseT& data)
                 {
                     auto obj = std::make_shared<Se3TrackerPoseTrackedT>();
                     obj->data = std::make_shared<Se3TrackerPoseT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly(
            "data", [](const Se3TrackerPoseTrackedT& self) -> std::shared_ptr<Se3TrackerPoseT> { return self.data; })
        .def("__repr__",
             [](const Se3TrackerPoseTrackedT& self) {
                 return std::string("Se3TrackerPoseTrackedT(data=") + (self.data ? "Se3TrackerPoseT(...)" : "None") + ")";
             });
}

} // namespace core
