// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Controller FlatBuffer schema.
// ControllerInputState, ControllerPose, ControllerSnapshot, DeviceDataTimestamp are structs.

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/controller_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_controller(py::module& m)
{
    // Bind DeviceDataTimestamp struct (if not already bound)
    if (!py::hasattr(m, "DeviceDataTimestamp"))
    {
        py::class_<DeviceDataTimestamp>(m, "DeviceDataTimestamp")
            .def(py::init<>())
            .def(py::init<int64_t, int64_t, int64_t>(), py::arg("sample_time_device_clock"),
                 py::arg("sample_time_common_clock"), py::arg("available_time_common_clock") = 0)
            .def_property_readonly("sample_time_device_clock", &DeviceDataTimestamp::sample_time_device_clock)
            .def_property_readonly("sample_time_common_clock", &DeviceDataTimestamp::sample_time_common_clock)
            .def_property_readonly("available_time_common_clock", &DeviceDataTimestamp::available_time_common_clock)
            .def("__repr__",
                 [](const DeviceDataTimestamp& self)
                 {
                     return "DeviceDataTimestamp(sample_time_device_clock=" +
                            std::to_string(self.sample_time_device_clock()) +
                            ", sample_time_common_clock=" + std::to_string(self.sample_time_common_clock()) +
                            ", available_time_common_clock=" + std::to_string(self.available_time_common_clock()) + ")";
                 });
    }

    // Bind ControllerInputState struct
    py::class_<ControllerInputState>(m, "ControllerInputState")
        .def(py::init<>())
        .def(py::init<bool, bool, bool, float, float, float, float>(), py::arg("primary_click"),
             py::arg("secondary_click"), py::arg("thumbstick_click"), py::arg("thumbstick_x"), py::arg("thumbstick_y"),
             py::arg("squeeze_value"), py::arg("trigger_value"))
        .def_property_readonly("primary_click", &ControllerInputState::primary_click)
        .def_property_readonly("secondary_click", &ControllerInputState::secondary_click)
        .def_property_readonly("thumbstick_click", &ControllerInputState::thumbstick_click)
        .def_property_readonly("thumbstick_x", &ControllerInputState::thumbstick_x)
        .def_property_readonly("thumbstick_y", &ControllerInputState::thumbstick_y)
        .def_property_readonly("squeeze_value", &ControllerInputState::squeeze_value)
        .def_property_readonly("trigger_value", &ControllerInputState::trigger_value)
        .def("__repr__",
             [](const ControllerInputState& self)
             {
                 return "ControllerInputState(primary=" + std::string(self.primary_click() ? "True" : "False") +
                        ", secondary=" + std::string(self.secondary_click() ? "True" : "False") + ", thumbstick=(" +
                        std::to_string(self.thumbstick_x()) + ", " + std::to_string(self.thumbstick_y()) + ")" +
                        ", squeeze=" + std::to_string(self.squeeze_value()) +
                        ", trigger=" + std::to_string(self.trigger_value()) + ")";
             });

    // Bind ControllerPose struct
    py::class_<ControllerPose>(m, "ControllerPose")
        .def(py::init<>())
        .def(py::init<const Pose&, bool>(), py::arg("pose"), py::arg("is_valid"))
        .def_property_readonly("pose", &ControllerPose::pose, py::return_value_policy::reference_internal)
        .def_property_readonly("is_valid", &ControllerPose::is_valid)
        .def("__repr__",
             [](const ControllerPose& self)
             {
                 std::string pose_str = "Pose(position=Point(x=" + std::to_string(self.pose().position().x()) +
                                        ", y=" + std::to_string(self.pose().position().y()) +
                                        ", z=" + std::to_string(self.pose().position().z()) +
                                        "), orientation=Quaternion(x=" + std::to_string(self.pose().orientation().x()) +
                                        ", y=" + std::to_string(self.pose().orientation().y()) +
                                        ", z=" + std::to_string(self.pose().orientation().z()) +
                                        ", w=" + std::to_string(self.pose().orientation().w()) + "))";

                 return "ControllerPose(pose=" + pose_str + ", is_valid=" + (self.is_valid() ? "True" : "False") + ")";
             });

    // Bind ControllerSnapshot struct (timestamp no longer embedded)
    py::class_<ControllerSnapshot>(m, "ControllerSnapshot")
        .def(py::init<>())
        .def(py::init<const ControllerPose&, const ControllerPose&, const ControllerInputState&, bool>(),
             py::arg("grip_pose"), py::arg("aim_pose"), py::arg("inputs"), py::arg("is_active"))
        .def_property_readonly("grip_pose", &ControllerSnapshot::grip_pose, py::return_value_policy::reference_internal)
        .def_property_readonly("aim_pose", &ControllerSnapshot::aim_pose, py::return_value_policy::reference_internal)
        .def_property_readonly("inputs", &ControllerSnapshot::inputs, py::return_value_policy::reference_internal)
        .def_property_readonly("is_active", &ControllerSnapshot::is_active)
        .def("__repr__",
             [](const ControllerSnapshot& self)
             {
                 std::string grip_str =
                     "ControllerPose(is_valid=" + std::string(self.grip_pose().is_valid() ? "True" : "False") + ")";
                 std::string aim_str =
                     "ControllerPose(is_valid=" + std::string(self.aim_pose().is_valid() ? "True" : "False") + ")";
                 return "ControllerSnapshot(grip_pose=" + grip_str + ", aim_pose=" + aim_str +
                        ", is_active=" + (self.is_active() ? "True" : "False") + ")";
             });
}

} // namespace core
