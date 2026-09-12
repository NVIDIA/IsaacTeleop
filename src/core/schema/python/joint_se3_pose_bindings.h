// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the JointSe3PoseOutput FlatBuffer schema.
// Types: JointName (enum), JointSe3Pose (struct) and JointSe3PoseOutput / ...Record (tables).

#pragma once

#include "pose_bindings.h"
#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/joint_se3_pose_generated.h>

#include <algorithm>
#include <memory>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_joint_se3_pose(py::module& m)
{
    py::enum_<JointName>(m, "JointName")
        .value("UNKNOWN", JointName_UNKNOWN)
        .value("HAND_RAW_THUMB_TIP", JointName_HAND_RAW_THUMB_TIP)
        .value("HAND_RAW_INDEX_TIP", JointName_HAND_RAW_INDEX_TIP)
        .value("HAND_RAW_MIDDLE_TIP", JointName_HAND_RAW_MIDDLE_TIP)
        .value("HAND_RAW_RING_TIP", JointName_HAND_RAW_RING_TIP)
        .value("HAND_RAW_LITTLE_TIP", JointName_HAND_RAW_LITTLE_TIP);

    py::class_<JointSe3Pose>(m, "JointSe3Pose", "One keyed joint pose.")
        .def(py::init<>())
        .def(py::init<JointName, const Pose&>(), py::arg("joint"), py::arg("pose"))
        .def_property_readonly("joint", &JointSe3Pose::joint)
        .def_property_readonly("pose", &JointSe3Pose::pose, py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const JointSe3Pose& self)
             {
                 return "JointSe3Pose(joint=" + std::string(EnumNameJointName(self.joint())) +
                        ", pose=" + pose_repr(self.pose()) + ")";
             });

    serialized_class<JointSe3PoseOutput>(
        m, "JointSe3PoseOutput",
        "Encoded per-frame tracker output: sparse joint poses keyed by JointName. A joint absent "
        "from joints is not tracked.")
        .def(py::init(
                 [](const std::vector<JointSe3Pose>& joints, const std::string& device_id)
                 {
                     JointSe3PoseOutputT native;
                     native.joints = joints;
                     // The wire contract is sorted-and-unique; sort here so Python callers cannot
                     // hand LookupByKey a vector it would silently mis-search.
                     std::sort(native.joints.begin(), native.joints.end(),
                               [](const JointSe3Pose& a, const JointSe3Pose& b) { return a.joint() < b.joint(); });
                     native.device_id = device_id;
                     return pack<JointSe3PoseOutput>(native);
                 }),
             py::arg("joints") = std::vector<JointSe3Pose>{}, py::arg("device_id") = std::string{},
             "Encode one frame of tracker poses. joints is sorted by JointName on the way in.")
        // Copied out by value: a JointSe3Pose is 32 bytes and these vectors are joint-count sized,
        // so this avoids handing Python pointers into the buffer.
        .def_property_readonly("joints",
                               [](const Serialized<JointSe3PoseOutput>& self)
                               {
                                   std::vector<JointSe3Pose> out;
                                   const auto* joints = self->joints();
                                   if (joints != nullptr)
                                   {
                                       out.reserve(joints->size());
                                       for (const auto* joint : *joints)
                                       {
                                           out.push_back(*joint);
                                       }
                                   }
                                   return out;
                               })
        .def_property_readonly("device_id", string_field(&JointSe3PoseOutput::device_id))
        .def(
            "lookup",
            [](const Serialized<JointSe3PoseOutput>& self, JointName joint) -> py::object
            {
                const auto* joints = self->joints();
                const auto* found = joints != nullptr ? joints->LookupByKey(joint) : nullptr;
                return found != nullptr ? py::cast(*found) : py::none();
            },
            py::arg("joint"), "Binary-search one joint by name; None when this device does not track it.")
        .def("__repr__",
             [](const Serialized<JointSe3PoseOutput>& self)
             {
                 const auto* device_id = self->device_id();
                 const auto* joints = self->joints();
                 return "JointSe3PoseOutput(device_id=" + (device_id != nullptr ? device_id->str() : std::string{}) +
                        ", joints=" + std::to_string(joints != nullptr ? joints->size() : 0) + ")";
             });

    bind_record<JointSe3PoseOutputRecord, JointSe3PoseOutput>(m, "JointSe3PoseOutputRecord", "JointSe3PoseOutput");
}

} // namespace core
