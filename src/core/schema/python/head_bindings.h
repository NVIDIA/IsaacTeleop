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
    // Bind HeadPoseT class (FlatBuffers object API for tables, read-only from Python).
    py::class_<HeadPoseT, std::unique_ptr<HeadPoseT>>(m, "HeadPoseT")
        .def(py::init<>())
        .def_property_readonly(
            "pose", [](const HeadPoseT& self) -> const Pose* { return self.pose.get(); },
            py::return_value_policy::reference_internal)
        .def_readonly("is_valid", &HeadPoseT::is_valid)
        .def_property_readonly(
            "timestamp", [](const HeadPoseT& self) -> const Timestamp* { return self.timestamp.get(); },
            py::return_value_policy::reference_internal)
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
                 std::string timestamp_str = "None";
                 if (self.timestamp)
                 {
                     timestamp_str = "Timestamp(device=" + std::to_string(self.timestamp->device_time()) +
                                     ", common=" + std::to_string(self.timestamp->common_time()) + ")";
                 }
                 return "HeadPoseT(pose=" + pose_str + ", is_valid=" + (self.is_valid ? "True" : "False") +
                        ", timestamp=" + timestamp_str + ")";
             });
}

} // namespace core
