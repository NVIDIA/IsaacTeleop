// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the FullBodyPose FlatBuffer schema.
// Includes BodyJointPose struct, BodyJoints struct, and FullBodyPoseT table.

#pragma once

#include "schema_array_views.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/full_body_generated.h>
#include <schema/timestamp_generated.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <memory>
#include <vector>

namespace py = pybind11;

namespace core
{

// First joint of a BodyJoints, i.e. the origin of the strided views below.
inline const BodyJointPose& first_body_joint(const py::object& self)
{
    return *(*self.cast<const BodyJoints&>().joints())[0];
}

// Row stride of the joint array; see the matching HandJoints constants.
constexpr py::ssize_t BODY_JOINT_STRIDE = static_cast<py::ssize_t>(sizeof(BodyJointPose));
constexpr py::ssize_t BODY_JOINT_COUNT = static_cast<py::ssize_t>(BodyJoint_NUM_JOINTS);

// The views span BODY_JOINT_COUNT rows of raw storage, so the enum count and the fixed array
// length declared in full_body.fbs must agree; otherwise the views would run off the struct.
static_assert(sizeof(BodyJoints) == sizeof(BodyJointPose) * static_cast<size_t>(BodyJoint_NUM_JOINTS),
              "BodyJoints.joints length must equal BodyJoint::NUM_JOINTS");

inline void bind_full_body(py::module& m)
{
    // Bind BodyJoint enum (joint indices for XR_BD_body_tracking).
    py::enum_<BodyJoint>(m, "BodyJoint")
        .value("PELVIS", BodyJoint_PELVIS)
        .value("LEFT_HIP", BodyJoint_LEFT_HIP)
        .value("RIGHT_HIP", BodyJoint_RIGHT_HIP)
        .value("SPINE1", BodyJoint_SPINE1)
        .value("LEFT_KNEE", BodyJoint_LEFT_KNEE)
        .value("RIGHT_KNEE", BodyJoint_RIGHT_KNEE)
        .value("SPINE2", BodyJoint_SPINE2)
        .value("LEFT_ANKLE", BodyJoint_LEFT_ANKLE)
        .value("RIGHT_ANKLE", BodyJoint_RIGHT_ANKLE)
        .value("SPINE3", BodyJoint_SPINE3)
        .value("LEFT_FOOT", BodyJoint_LEFT_FOOT)
        .value("RIGHT_FOOT", BodyJoint_RIGHT_FOOT)
        .value("NECK", BodyJoint_NECK)
        .value("LEFT_COLLAR", BodyJoint_LEFT_COLLAR)
        .value("RIGHT_COLLAR", BodyJoint_RIGHT_COLLAR)
        .value("HEAD", BodyJoint_HEAD)
        .value("LEFT_SHOULDER", BodyJoint_LEFT_SHOULDER)
        .value("RIGHT_SHOULDER", BodyJoint_RIGHT_SHOULDER)
        .value("LEFT_ELBOW", BodyJoint_LEFT_ELBOW)
        .value("RIGHT_ELBOW", BodyJoint_RIGHT_ELBOW)
        .value("LEFT_WRIST", BodyJoint_LEFT_WRIST)
        .value("RIGHT_WRIST", BodyJoint_RIGHT_WRIST)
        .value("LEFT_HAND", BodyJoint_LEFT_HAND)
        .value("RIGHT_HAND", BodyJoint_RIGHT_HAND)
        .value("NUM_JOINTS", BodyJoint_NUM_JOINTS);

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

    // Bind BodyJoints struct (fixed-size array of 24 BodyJointPose).
    py::class_<BodyJoints>(m, "BodyJoints")
        .def(py::init<>())
        .def(
            "joints",
            [](const BodyJoints& self, size_t index) -> const BodyJointPose*
            {
                if (index >= static_cast<size_t>(BodyJoint_NUM_JOINTS))
                {
                    throw py::index_error("BodyJoints index out of range (must be 0-23)");
                }
                return (*self.joints())[index];
            },
            py::arg("index"), py::return_value_policy::reference_internal,
            "Get the BodyJointPose at the specified index (0 to NUM_JOINTS-1).")
        // Zero-copy bulk accessors, one per joint field; see the matching note on HandJoints.
        // One fewer than the hand, since BodyJointPose has no radius.
        .def_property_readonly(
            "positions",
            [](py::object self)
            {
                const auto* first = reinterpret_cast<const float*>(&first_body_joint(self).pose().position());
                return strided_field_view<float>(self, first, BODY_JOINT_STRIDE, BODY_JOINT_COUNT, 3);
            },
            "Joint positions as a (NUM_JOINTS, 3) float32 view in BodyJoint order. Strided (not contiguous) "
            "and aliasing this object's storage: writing to it modifies the schema object; call .copy() for "
            "packed data you own.")
        .def_property_readonly(
            "orientations",
            [](py::object self)
            {
                const auto* first = reinterpret_cast<const float*>(&first_body_joint(self).pose().orientation());
                return strided_field_view<float>(self, first, BODY_JOINT_STRIDE, BODY_JOINT_COUNT, 4);
            },
            "Joint orientation quaternions (XYZW) as a (NUM_JOINTS, 4) float32 view. See positions for the "
            "aliasing and stride caveats.")
        .def_property_readonly(
            "is_valid",
            [offset = FBS_FIELD_OFFSET(BodyJointPose, is_valid)](py::object self)
            {
                const auto* first = fbs_field_address<uint8_t>(first_body_joint(self), offset);
                return strided_field_view<uint8_t>(self, first, BODY_JOINT_STRIDE, BODY_JOINT_COUNT, 0);
            },
            "Per-joint validity as a (NUM_JOINTS,) uint8 view. See positions for the aliasing and stride "
            "caveats.")
        .def("__repr__", [](const BodyJoints&) { return "BodyJoints(joints=[...24 BodyJointPose entries...])"; });

    // Bind FullBodyPoseT class (FlatBuffers object API for tables).
    py::class_<FullBodyPoseT, std::shared_ptr<FullBodyPoseT>>(m, "FullBodyPoseT")
        .def(py::init(
            []()
            {
                auto obj = std::make_shared<FullBodyPoseT>();
                obj->joints = std::make_shared<BodyJoints>();
                return obj;
            }))
        .def(py::init(
                 [](const BodyJoints& joints)
                 {
                     auto obj = std::make_shared<FullBodyPoseT>();
                     obj->joints = std::make_shared<BodyJoints>(joints);
                     return obj;
                 }),
             py::arg("joints"))
        .def_property_readonly(
            "joints", [](const FullBodyPoseT& self) -> const BodyJoints* { return self.joints.get(); },
            py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const FullBodyPoseT& self)
             {
                 std::string joints_str = "None";
                 if (self.joints)
                 {
                     joints_str = "BodyJoints(joints=[...24 entries...])";
                 }
                 return "FullBodyPoseT(joints=" + joints_str + ")";
             });

    py::class_<FullBodyPoseRecordT, std::shared_ptr<FullBodyPoseRecordT>>(m, "FullBodyPoseRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const FullBodyPoseT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<FullBodyPoseRecordT>();
                     obj->data = std::make_shared<FullBodyPoseT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly(
            "data", [](const FullBodyPoseRecordT& self) -> std::shared_ptr<FullBodyPoseT> { return self.data; })
        .def_readonly("timestamp", &FullBodyPoseRecordT::timestamp)
        .def("__repr__", [](const FullBodyPoseRecordT& self)
             { return "FullBodyPoseRecord(data=" + std::string(self.data ? "FullBodyPoseT(...)" : "None") + ")"; });

    py::class_<FullBodyPoseTrackedT, std::shared_ptr<FullBodyPoseTrackedT>>(m, "FullBodyPoseTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const FullBodyPoseT& data)
                 {
                     auto obj = std::make_shared<FullBodyPoseTrackedT>();
                     obj->data = std::make_shared<FullBodyPoseT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly(
            "data", [](const FullBodyPoseTrackedT& self) -> std::shared_ptr<FullBodyPoseT> { return self.data; })
        .def("__repr__", [](const FullBodyPoseTrackedT& self)
             { return std::string("FullBodyPoseTrackedT(data=") + (self.data ? "FullBodyPoseT(...)" : "None") + ")"; });
}

} // namespace core
