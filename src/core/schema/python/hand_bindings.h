// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the HandPose FlatBuffer schema.
// Includes HandJointPose struct, HandJoints struct, and HandPoseT table.

#pragma once

#include "pose_bindings.h"
#include "schema_array_views.h"
#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/hand_generated.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

// First joint of a HandJoints, i.e. the origin of the strided views below.
inline const HandJointPose& first_hand_joint(const py::object& self)
{
    return *(*self.cast<const HandJoints&>().poses())[0];
}

// Row stride of the joint array: the joints are a contiguous array of structs, so one whole
// HandJointPose separates a field from the same field of the next joint.
constexpr py::ssize_t HAND_JOINT_STRIDE = static_cast<py::ssize_t>(sizeof(HandJointPose));
constexpr py::ssize_t HAND_JOINT_COUNT = static_cast<py::ssize_t>(HandJoint_NUM_JOINTS);

// The views span HAND_JOINT_COUNT rows of raw storage, so the enum count and the fixed array
// length declared in hand.fbs must agree; otherwise the views would run off the struct.
static_assert(sizeof(HandJoints) == sizeof(HandJointPose) * static_cast<size_t>(HandJoint_NUM_JOINTS),
              "HandJoints.poses length must equal HandJoint::NUM_JOINTS");

inline void bind_hand(py::module& m)
{
    // Bind HandJoint enum (indices align with OpenXR XrHandJointEXT; see hand.fbs).
    py::enum_<HandJoint>(m, "HandJoint")
        .value("PALM", HandJoint_PALM)
        .value("WRIST", HandJoint_WRIST)
        .value("THUMB_METACARPAL", HandJoint_THUMB_METACARPAL)
        .value("THUMB_PROXIMAL", HandJoint_THUMB_PROXIMAL)
        .value("THUMB_DISTAL", HandJoint_THUMB_DISTAL)
        .value("THUMB_TIP", HandJoint_THUMB_TIP)
        .value("INDEX_METACARPAL", HandJoint_INDEX_METACARPAL)
        .value("INDEX_PROXIMAL", HandJoint_INDEX_PROXIMAL)
        .value("INDEX_INTERMEDIATE", HandJoint_INDEX_INTERMEDIATE)
        .value("INDEX_DISTAL", HandJoint_INDEX_DISTAL)
        .value("INDEX_TIP", HandJoint_INDEX_TIP)
        .value("MIDDLE_METACARPAL", HandJoint_MIDDLE_METACARPAL)
        .value("MIDDLE_PROXIMAL", HandJoint_MIDDLE_PROXIMAL)
        .value("MIDDLE_INTERMEDIATE", HandJoint_MIDDLE_INTERMEDIATE)
        .value("MIDDLE_DISTAL", HandJoint_MIDDLE_DISTAL)
        .value("MIDDLE_TIP", HandJoint_MIDDLE_TIP)
        .value("RING_METACARPAL", HandJoint_RING_METACARPAL)
        .value("RING_PROXIMAL", HandJoint_RING_PROXIMAL)
        .value("RING_INTERMEDIATE", HandJoint_RING_INTERMEDIATE)
        .value("RING_DISTAL", HandJoint_RING_DISTAL)
        .value("RING_TIP", HandJoint_RING_TIP)
        .value("LITTLE_METACARPAL", HandJoint_LITTLE_METACARPAL)
        .value("LITTLE_PROXIMAL", HandJoint_LITTLE_PROXIMAL)
        .value("LITTLE_INTERMEDIATE", HandJoint_LITTLE_INTERMEDIATE)
        .value("LITTLE_DISTAL", HandJoint_LITTLE_DISTAL)
        .value("LITTLE_TIP", HandJoint_LITTLE_TIP)
        .value("NUM_JOINTS", HandJoint_NUM_JOINTS);

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
                 return "HandJointPose(pose=" + pose_repr(self.pose()) +
                        ", is_valid=" + (self.is_valid() ? "True" : "False") +
                        ", radius=" + std::to_string(self.radius()) + ")";
             });

    // Bind HandJoints struct (fixed-size array; length matches HandJoint::NUM_JOINTS).
    py::class_<HandJoints>(m, "HandJoints")
        .def(py::init<>())
        .def(
            "poses",
            [](const HandJoints& self, size_t index) -> const HandJointPose*
            {
                if (index >= static_cast<size_t>(HandJoint_NUM_JOINTS))
                {
                    throw py::index_error("HandJoints index out of range (must be 0-" +
                                          std::to_string(static_cast<int>(HandJoint_NUM_JOINTS) - 1) + ")");
                }
                return (*self.poses())[index];
            },
            py::arg("index"), py::return_value_policy::reference_internal,
            "Get the HandJointPose at the specified index. Valid indices: 0 <= index < HandJoint.NUM_JOINTS "
            "(OpenXR hand joint order).")
        // Zero-copy bulk accessors, one per joint field: strided views aliasing this object's
        // storage. See schema_array_views.h for the mechanics and for why they are writable.
        // Rows are in HandJoint / OpenXR joint order.
        //
        // positions and orientations take the address of the generated accessor, so the
        // compiler derives the location and a schema rename breaks the build. radius and
        // is_valid are returned by value by flatc and have no address, so those two resolve
        // an offset once here via FBS_FIELD_OFFSET, which keeps the name compile-time checked.
        .def_property_readonly(
            "positions",
            [](py::object self)
            {
                const auto* first = reinterpret_cast<const float*>(&first_hand_joint(self).pose().position());
                return strided_field_view<float>(self, first, HAND_JOINT_STRIDE, HAND_JOINT_COUNT, 3);
            },
            "Joint positions as a (NUM_JOINTS, 3) float32 view. Strided (not contiguous) and aliasing this "
            "object's storage: writing to it modifies the schema object; call .copy() for packed data you own.")
        .def_property_readonly(
            "orientations",
            [](py::object self)
            {
                const auto* first = reinterpret_cast<const float*>(&first_hand_joint(self).pose().orientation());
                return strided_field_view<float>(self, first, HAND_JOINT_STRIDE, HAND_JOINT_COUNT, 4);
            },
            "Joint orientation quaternions (XYZW) as a (NUM_JOINTS, 4) float32 view. See positions for the "
            "aliasing and stride caveats.")
        .def_property_readonly(
            "radii",
            [offset = FBS_FIELD_OFFSET(HandJointPose, radius)](py::object self)
            {
                const auto* first = fbs_field_address<float>(first_hand_joint(self), offset);
                return strided_field_view<float>(self, first, HAND_JOINT_STRIDE, HAND_JOINT_COUNT, 0);
            },
            "Joint radii as a (NUM_JOINTS,) float32 view. See positions for the aliasing and stride caveats.")
        .def_property_readonly(
            "is_valid",
            [offset = FBS_FIELD_OFFSET(HandJointPose, is_valid)](py::object self)
            {
                const auto* first = fbs_field_address<uint8_t>(first_hand_joint(self), offset);
                return strided_field_view<uint8_t>(self, first, HAND_JOINT_STRIDE, HAND_JOINT_COUNT, 0);
            },
            "Per-joint validity as a (NUM_JOINTS,) uint8 view. See positions for the aliasing and stride "
            "caveats.")
        .def("__repr__",
             [](const HandJoints&) { return "HandJoints(poses=[...HandJoint.NUM_JOINTS HandJointPose entries...])"; });

    serialized_class<HandPose>(m, "HandPose", "Encoded hand pose: 26 joints in HandJoint / OpenXR order.")
        .def(py::init(
                 [](const HandJoints& joints)
                 {
                     HandPoseT native;
                     native.joints = std::make_shared<HandJoints>(joints);
                     return pack<HandPose>(native);
                 }),
             py::arg("joints") = HandJoints(), "Encode a hand pose. Defaults to all-zero joints.")
        .def_property_readonly("joints", field(&HandPose::joints), py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const Serialized<HandPose>& self)
             {
                 const std::string joints_str =
                     self->joints() != nullptr ? "HandJoints(poses=[...26 entries...])" : "None";
                 return "HandPose(joints=" + joints_str + ")";
             });

    bind_record<HandPoseRecord, HandPose>(m, "HandPoseRecord", "HandPose");
}

} // namespace core
