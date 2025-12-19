// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the HeadPose FlatBuffer schema.
// HeadPoseT is a table type (mutable object-API) with pose, is_valid, and timestamp fields.

#pragma once

#include <pybind11/pybind11.h>
#include <schema/head_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_head(py::module& m)
{
    // Bind HeadPoseT class (FlatBuffers object API for tables).
    py::class_<HeadPoseT, std::unique_ptr<HeadPoseT>>(m, "HeadPoseT")
        .def(py::init<>())
        .def_property_readonly(
            "pose", [](const HeadPoseT& self) -> const Pose* { return self.pose.get(); },
            py::return_value_policy::reference_internal)
        .def_readwrite("is_valid", &HeadPoseT::is_valid)
        .def_readwrite("timestamp", &HeadPoseT::timestamp)
        // Convenience method to set pose from components.
        .def(
            "set_pose",
            [](HeadPoseT& self, const Point& position, const Quaternion& orientation)
            { self.pose = std::make_unique<Pose>(position, orientation); },
            py::arg("position"), py::arg("orientation"), "Set the pose from position and orientation components.")
        .def("__repr__",
             [](const HeadPoseT& self)
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
                 return "HeadPoseT(pose=" + pose_str + ", is_valid=" + (self.is_valid ? "True" : "False") +
                        ", timestamp=" + std::to_string(self.timestamp) + ")";
             });
}

} // namespace core
