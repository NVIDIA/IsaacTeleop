// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the HandPose FlatBuffer schema.
// Includes HandJointPose struct, HandJoints struct, and HandPoseT table.

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/hand_generated.h>

#include <array>
#include <cstring>
#include <memory>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_hand(py::module& m)
{
    // Bind HandJointPose struct (pose, is_valid, radius).
    py::class_<HandJointPose>(m, "HandJointPose")
        .def(py::init<>())
        .def(py::init<const Pose&, bool, float>(), py::arg("pose"), py::arg("is_valid") = false, py::arg("radius") = 0.0f)
        .def_property_readonly("pose", &HandJointPose::pose, py::return_value_policy::reference_internal)
        .def_property_readonly("is_valid", &HandJointPose::is_valid)
        .def_property_readonly("radius", &HandJointPose::radius)
        .def("__repr__",
             [](const HandJointPose& self)
             {
                 return "HandJointPose(pose=Pose(position=Point(x=" + std::to_string(self.pose().position().x()) +
                        ", y=" + std::to_string(self.pose().position().y()) +
                        ", z=" + std::to_string(self.pose().position().z()) +
                        "), orientation=Quaternion(x=" + std::to_string(self.pose().orientation().x()) +
                        ", y=" + std::to_string(self.pose().orientation().y()) +
                        ", z=" + std::to_string(self.pose().orientation().z()) +
                        ", w=" + std::to_string(self.pose().orientation().w()) +
                        ")), is_valid=" + (self.is_valid() ? "True" : "False") +
                        ", radius=" + std::to_string(self.radius()) + ")";
             });

    // Bind HandJoints struct (fixed-size array of 26 HandJointPose).
    py::class_<HandJoints>(m, "HandJoints")
        .def(py::init<>())
        .def(
            "poses",
            [](const HandJoints& self, size_t index) -> const HandJointPose*
            {
                if (index >= 26)
                {
                    throw py::index_error("HandJoints index out of range (must be 0-25)");
                }
                return (*self.poses())[index];
            },
            py::arg("index"), py::return_value_policy::reference_internal,
            "Get the HandJointPose at the specified index (0-25).")
        .def("__repr__", [](const HandJoints&) { return "HandJoints(poses=[...26 HandJointPose entries...])"; });

    // Bind HandPoseT class (FlatBuffers object API for tables).
    py::class_<HandPoseT, std::shared_ptr<HandPoseT>>(m, "HandPoseT")
        .def(py::init(
            []()
            {
                auto obj = std::make_shared<HandPoseT>();
                obj->joints = std::make_shared<HandJoints>();
                obj->timestamp = std::make_shared<Timestamp>();
                return obj;
            }))
        .def(py::init(
                 [](const HandJoints& joints, const Timestamp& timestamp)
                 {
                     auto obj = std::make_shared<HandPoseT>();
                     obj->joints = std::make_shared<HandJoints>(joints);
                     obj->timestamp = std::make_shared<Timestamp>(timestamp);
                     return obj;
                 }),
             py::arg("joints"), py::arg("timestamp"))
        .def_property_readonly(
            "joints", [](const HandPoseT& self) -> const HandJoints* { return self.joints.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "timestamp", [](const HandPoseT& self) -> const Timestamp* { return self.timestamp.get(); },
            py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const HandPoseT& self)
             {
                 std::string joints_str = "None";
                 if (self.joints)
                 {
                     joints_str = "HandJoints(poses=[...26 entries...])";
                 }
                 std::string timestamp_str = "None";
                 if (self.timestamp)
                 {
                     timestamp_str = "Timestamp(device=" + std::to_string(self.timestamp->device_time()) +
                                     ", common=" + std::to_string(self.timestamp->common_time()) + ")";
                 }
                 return "HandPoseT(joints=" + joints_str + ", timestamp=" + timestamp_str + ")";
             });

    py::class_<HandPoseTrackedT>(m, "HandPoseTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const HandPoseT& data)
                 {
                     auto obj = std::make_unique<HandPoseTrackedT>();
                     obj->data = std::make_shared<HandPoseT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly(
            "data", [](const HandPoseTrackedT& self) -> std::shared_ptr<HandPoseT> { return self.data; })
        .def("__repr__", [](const HandPoseTrackedT& self)
             { return std::string("HandPoseTrackedT(data=") + (self.data ? "HandPoseT(...)" : "None") + ")"; });
}

} // namespace core
