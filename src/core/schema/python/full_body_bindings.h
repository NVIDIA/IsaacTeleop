// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the FullBodyPosePico FlatBuffer schema.
// Includes BodyJointPose struct, BodyJointsPico struct, and FullBodyPosePicoT table.

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/full_body_generated.h>

#include <array>
#include <cstring>
#include <memory>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_full_body(py::module& m)
{
    // Bind BodyJointPico enum (joint indices for XR_BD_body_tracking).
    py::enum_<BodyJointPico>(m, "BodyJointPico")
        .value("PELVIS", BodyJointPico_PELVIS)
        .value("LEFT_HIP", BodyJointPico_LEFT_HIP)
        .value("RIGHT_HIP", BodyJointPico_RIGHT_HIP)
        .value("SPINE1", BodyJointPico_SPINE1)
        .value("LEFT_KNEE", BodyJointPico_LEFT_KNEE)
        .value("RIGHT_KNEE", BodyJointPico_RIGHT_KNEE)
        .value("SPINE2", BodyJointPico_SPINE2)
        .value("LEFT_ANKLE", BodyJointPico_LEFT_ANKLE)
        .value("RIGHT_ANKLE", BodyJointPico_RIGHT_ANKLE)
        .value("SPINE3", BodyJointPico_SPINE3)
        .value("LEFT_FOOT", BodyJointPico_LEFT_FOOT)
        .value("RIGHT_FOOT", BodyJointPico_RIGHT_FOOT)
        .value("NECK", BodyJointPico_NECK)
        .value("LEFT_COLLAR", BodyJointPico_LEFT_COLLAR)
        .value("RIGHT_COLLAR", BodyJointPico_RIGHT_COLLAR)
        .value("HEAD", BodyJointPico_HEAD)
        .value("LEFT_SHOULDER", BodyJointPico_LEFT_SHOULDER)
        .value("RIGHT_SHOULDER", BodyJointPico_RIGHT_SHOULDER)
        .value("LEFT_ELBOW", BodyJointPico_LEFT_ELBOW)
        .value("RIGHT_ELBOW", BodyJointPico_RIGHT_ELBOW)
        .value("LEFT_WRIST", BodyJointPico_LEFT_WRIST)
        .value("RIGHT_WRIST", BodyJointPico_RIGHT_WRIST)
        .value("LEFT_HAND", BodyJointPico_LEFT_HAND)
        .value("RIGHT_HAND", BodyJointPico_RIGHT_HAND)
        .value("NUM_JOINTS", BodyJointPico_NUM_JOINTS);

    // Bind BodyJointPose struct (pose, is_valid).
    py::class_<BodyJointPose>(m, "BodyJointPose")
        .def(py::init<>())
        .def(py::init<const Pose&, bool>(), py::arg("pose"), py::arg("is_valid") = false)
        .def_property_readonly("pose", &BodyJointPose::pose, py::return_value_policy::reference_internal)
        .def_property_readonly("is_valid", &BodyJointPose::is_valid)
        .def("__repr__",
             [](const BodyJointPose& self)
             {
                 return "BodyJointPose(pose=Pose(position=Point(x=" + std::to_string(self.pose().position().x()) +
                        ", y=" + std::to_string(self.pose().position().y()) +
                        ", z=" + std::to_string(self.pose().position().z()) +
                        "), orientation=Quaternion(x=" + std::to_string(self.pose().orientation().x()) +
                        ", y=" + std::to_string(self.pose().orientation().y()) +
                        ", z=" + std::to_string(self.pose().orientation().z()) +
                        ", w=" + std::to_string(self.pose().orientation().w()) +
                        ")), is_valid=" + (self.is_valid() ? "True" : "False") + ")";
             });

    // Bind BodyJointsPico struct (fixed-size array of 24 BodyJointPose).
    py::class_<BodyJointsPico>(m, "BodyJointsPico")
        .def(py::init<>())
        .def(
            "joints",
            [](const BodyJointsPico& self, size_t index) -> const BodyJointPose*
            {
                if (index >= static_cast<size_t>(BodyJointPico_NUM_JOINTS))
                {
                    throw py::index_error("BodyJointsPico index out of range (must be 0-23)");
                }
                return (*self.joints())[index];
            },
            py::arg("index"), py::return_value_policy::reference_internal,
            "Get the BodyJointPose at the specified index (0 to NUM_JOINTS-1).")
        .def("__len__", [](const BodyJointsPico&) { return static_cast<size_t>(BodyJointPico_NUM_JOINTS); })
        .def(
            "__getitem__",
            [](const BodyJointsPico& self, size_t index) -> const BodyJointPose*
            {
                if (index >= static_cast<size_t>(BodyJointPico_NUM_JOINTS))
                {
                    throw py::index_error("BodyJointsPico index out of range (must be 0-" +
                                          std::to_string(BodyJointPico_NUM_JOINTS - 1) + ")");
                }
                return (*self.joints())[index];
            },
            py::return_value_policy::reference_internal)
        .def("__repr__", [](const BodyJointsPico&) { return "BodyJointsPico(joints=[...24 BodyJointPose entries...])"; });

    // Bind FullBodyPosePicoT class (FlatBuffers object API for tables, read-only from Python).
    py::class_<FullBodyPosePicoT, std::unique_ptr<FullBodyPosePicoT>>(m, "FullBodyPosePicoT")
        .def(py::init<>())
        .def_property_readonly(
            "joints", [](const FullBodyPosePicoT& self) -> const BodyJointsPico* { return self.joints.get(); },
            py::return_value_policy::reference_internal)
        .def_readonly("is_active", &FullBodyPosePicoT::is_active)
        .def_property_readonly(
            "timestamp", [](const FullBodyPosePicoT& self) -> const Timestamp* { return self.timestamp.get(); },
            py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const FullBodyPosePicoT& self)
             {
                 std::string joints_str = "None";
                 if (self.joints)
                 {
                     joints_str = "BodyJointsPico(joints=[...24 entries...])";
                 }
                 std::string timestamp_str = "None";
                 if (self.timestamp)
                 {
                     timestamp_str = "Timestamp(device=" + std::to_string(self.timestamp->device_time()) +
                                     ", common=" + std::to_string(self.timestamp->common_time()) + ")";
                 }
                 return "FullBodyPosePicoT(joints=" + joints_str +
                        ", is_active=" + (self.is_active ? "True" : "False") + ", timestamp=" + timestamp_str + ")";
             });
}

} // namespace core
