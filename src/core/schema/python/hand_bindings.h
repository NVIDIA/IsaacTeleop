// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the HandPose FlatBuffer schema.
// Includes HandJointPose struct and HandPose struct.

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

    // Bind HandPose struct (read-only from Python, exposed as HandPoseT for backward compat).
    py::class_<HandPose>(m, "HandPoseT")
        .def(py::init<>())
        .def_property_readonly("is_active", &HandPose::is_active)
        .def_property_readonly(
            "timestamp", [](const HandPose& self) -> const Timestamp& { return self.timestamp(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly("num_joints", [](const HandPose& self) { return self.joints()->size(); })
        .def(
            "joint",
            [](const HandPose& self, size_t index) -> const HandJointPose*
            {
                if (index >= 26)
                {
                    throw py::index_error("Joint index out of range (must be 0-25)");
                }
                return (*self.joints())[index];
            },
            py::arg("index"), py::return_value_policy::reference_internal,
            "Get the HandJointPose at the specified index (0-25).")
        .def("joints",
             [](const HandPose& self) -> py::list
             {
                 py::list result;
                 for (size_t i = 0; i < self.joints()->size(); ++i)
                 {
                     result.append(py::cast(*(*self.joints())[i]));
                 }
                 return result;
             })
        .def("__repr__",
             [](const HandPose& self)
             {
                 return "HandPoseT(" + std::to_string(self.joints()->size()) + " joints" +
                        ", is_active=" + (self.is_active() ? "True" : "False") +
                        ", timestamp=Timestamp(device=" + std::to_string(self.timestamp().device_time()) +
                        ", common=" + std::to_string(self.timestamp().common_time()) + "))";
             });
}

} // namespace core
