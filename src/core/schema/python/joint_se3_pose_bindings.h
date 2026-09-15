// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the JointSe3PoseOutput FlatBuffer schema.
// Types: JointName (enum), JointSe3Pose (struct) and JointSe3PoseOutput / ...Record (tables).

#pragma once

#include "pose_bindings.h"
#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/joint_se3_pose_family.hpp>
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
    py::enum_<JointType>(m, "JointType")
        .value("UNKNOWN", JointType_UNKNOWN)
        .value("HAND_OPENXR", JointType_HAND_OPENXR)
        .value("HAND_RAW", JointType_HAND_RAW);

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
                 [](JointType type, const std::vector<JointSe3Pose>& joints, const std::string& device_id)
                 {
                     JointSe3PoseOutputT native;
                     native.type = type;
                     native.joints = joints;
                     // The wire contract is sorted-and-unique; sort here so Python callers cannot
                     // hand LookupByKey a vector it would silently mis-search.
                     std::sort(native.joints.begin(), native.joints.end(),
                               [](const JointSe3Pose& a, const JointSe3Pose& b) { return a.joint() < b.joint(); });
                     // Sorting does not make the keys unique, and LookupByKey cannot say which of
                     // two equal keys it landed on.
                     const auto duplicate = std::adjacent_find(native.joints.begin(), native.joints.end(),
                                                               [](const JointSe3Pose& a, const JointSe3Pose& b)
                                                               { return a.joint() == b.joint(); });
                     if (duplicate != native.joints.end())
                     {
                         throw py::value_error("joints: duplicate JointName " +
                                               std::string(EnumNameJointName(duplicate->joint())));
                     }
                     // One frame carries one family. type is redundant with the keys by
                     // construction, so disagreement is a writer bug rather than a choice, and
                     // UNKNOWN names no family -- it fits only a frame with no keys to name.
                     if (type == JointType_UNKNOWN && !native.joints.empty())
                     {
                         throw py::value_error("type: UNKNOWN is only valid when joints is empty");
                     }
                     for (const JointSe3Pose& joint : native.joints)
                     {
                         if (joint_family(joint.joint()) != type)
                         {
                             throw py::value_error("joints: " + std::string(EnumNameJointName(joint.joint())) +
                                                   " is not in the " + std::string(EnumNameJointType(type)) + " block");
                         }
                     }
                     native.device_id = device_id;
                     return pack<JointSe3PoseOutput>(native);
                 }),
             py::arg("type") = JointType_UNKNOWN, py::arg("joints") = std::vector<JointSe3Pose>{},
             py::arg("device_id") = std::string{},
             "Encode one frame of tracker poses. joints is sorted by JointName on the way in; "
             "duplicate keys, a type that does not match them, or a non-empty frame left "
             "UNKNOWN, all raise ValueError.")
        .def_property_readonly("type", field(&JointSe3PoseOutput::type))
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
                 return "JointSe3PoseOutput(type=" + std::string(EnumNameJointType(self->type())) +
                        ", device_id=" + (device_id != nullptr ? device_id->str() : std::string{}) +
                        ", joints=" + std::to_string(joints != nullptr ? joints->size() : 0) + ")";
             });

    bind_record<JointSe3PoseOutputRecord, JointSe3PoseOutput>(m, "JointSe3PoseOutputRecord", "JointSe3PoseOutput");
}

} // namespace core
