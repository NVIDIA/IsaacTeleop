// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the HeadPose FlatBuffer schema.
// HeadPose is a struct with pose, is_valid, and timestamp fields.

#pragma once

#include <pybind11/pybind11.h>
#include <schema/head_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_head(py::module& m)
{
    // Bind HeadPose struct (read-only from Python, exposed as HeadPoseT for backward compat).
    py::class_<HeadPose>(m, "HeadPoseT")
        .def(py::init<>())
        .def_property_readonly(
            "pose", [](const HeadPose& self) -> const Pose& { return self.pose(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly("is_valid", &HeadPose::is_valid)
        .def_property_readonly(
            "timestamp", [](const HeadPose& self) -> const Timestamp& { return self.timestamp(); },
            py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const HeadPose& self)
             {
                 std::string pose_str = "Pose(position=Point(x=" + std::to_string(self.pose().position().x()) +
                                        ", y=" + std::to_string(self.pose().position().y()) +
                                        ", z=" + std::to_string(self.pose().position().z()) +
                                        "), orientation=Quaternion(x=" + std::to_string(self.pose().orientation().x()) +
                                        ", y=" + std::to_string(self.pose().orientation().y()) +
                                        ", z=" + std::to_string(self.pose().orientation().z()) +
                                        ", w=" + std::to_string(self.pose().orientation().w()) + "))";
                 return "HeadPoseT(pose=" + pose_str + ", is_valid=" + (self.is_valid() ? "True" : "False") +
                        ", timestamp=Timestamp(device=" + std::to_string(self.timestamp().device_time()) +
                        ", common=" + std::to_string(self.timestamp().common_time()) + "))";
             });
}

} // namespace core
