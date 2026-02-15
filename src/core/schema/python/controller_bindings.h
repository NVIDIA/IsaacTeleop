// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Controller FlatBuffer schema.
// ControllerInputState, ControllerPose, Timestamp are structs.
// ControllerSnapshotT and ControllerDataT are tables (native types).

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
    // Bind Timestamp struct (if not already bound)
    if (!py::hasattr(m, "Timestamp"))
    {
        py::class_<Timestamp>(m, "Timestamp")
            .def(py::init<>())
            .def(py::init<int64_t, int64_t>(), py::arg("device_time"), py::arg("common_time"))
            .def_property_readonly("device_time", &Timestamp::device_time)
            .def_property_readonly("common_time", &Timestamp::common_time)
            .def("__repr__",
                 [](const Timestamp& self)
                 {
                     return "Timestamp(device_time=" + std::to_string(self.device_time()) +
                            ", common_time=" + std::to_string(self.common_time()) + ")";
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

    // Bind ControllerPose struct (generated ctor is bool is_valid, const Pose& pose)
    py::class_<ControllerPose>(m, "ControllerPose")
        .def(py::init<>())
        .def(py::init([](bool is_valid, const Pose& pose) { return ControllerPose(is_valid, pose); }),
             py::arg("is_valid"), py::arg("pose"))
        .def_property_readonly("is_valid", &ControllerPose::is_valid)
        .def_property_readonly("pose", &ControllerPose::pose, py::return_value_policy::reference_internal)
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

                 return std::string("ControllerPose(is_valid=") + (self.is_valid() ? "True" : "False") +
                        ", pose=" + pose_str + ")";
             });

    // Bind ControllerSnapshotT (table native type) as "ControllerSnapshot" for Python
    py::class_<ControllerSnapshotT, std::unique_ptr<ControllerSnapshotT>>(m, "ControllerSnapshot")
        .def(py::init<>())
        .def(py::init(
                 [](bool is_valid, const ControllerPose& grip_pose, const ControllerPose& aim_pose,
                    const ControllerInputState& inputs, const Timestamp& timestamp)
                 {
                     auto t = std::make_unique<ControllerSnapshotT>();
                     t->is_valid = is_valid;
                     t->grip_pose = std::make_shared<ControllerPose>(grip_pose);
                     t->aim_pose = std::make_shared<ControllerPose>(aim_pose);
                     t->inputs = std::make_shared<ControllerInputState>(inputs);
                     t->timestamp = std::make_shared<Timestamp>(timestamp);
                     return t;
                 }),
             py::arg("is_valid"), py::arg("grip_pose"), py::arg("aim_pose"), py::arg("inputs"), py::arg("timestamp"))
        .def_readonly("is_valid", &ControllerSnapshotT::is_valid)
        .def_property_readonly(
            "grip_pose", [](const ControllerSnapshotT& self) -> const ControllerPose* { return self.grip_pose.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "aim_pose", [](const ControllerSnapshotT& self) -> const ControllerPose* { return self.aim_pose.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "inputs", [](const ControllerSnapshotT& self) -> const ControllerInputState* { return self.inputs.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "timestamp", [](const ControllerSnapshotT& self) -> const Timestamp* { return self.timestamp.get(); },
            py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const ControllerSnapshotT& self)
             {
                 std::string grip_str =
                     self.grip_pose ?
                         ("ControllerPose(is_valid=" + std::string(self.grip_pose->is_valid() ? "True" : "False") + ")") :
                         "None";
                 std::string aim_str =
                     self.aim_pose ?
                         ("ControllerPose(is_valid=" + std::string(self.aim_pose->is_valid() ? "True" : "False") + ")") :
                         "None";
                 return std::string("ControllerSnapshot(is_valid=") + (self.is_valid ? "True" : "False") +
                        ", grip_pose=" + grip_str + ", aim_pose=" + aim_str + ")";
             });

    // Bind ControllerDataT class (table native type - root object, read-only from Python)
    py::class_<ControllerDataT, std::unique_ptr<ControllerDataT>>(m, "ControllerData")
        .def(py::init<>())
        .def_property_readonly(
            "left_controller",
            [](const ControllerDataT& self) -> const ControllerSnapshotT* { return self.left_controller.get(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "right_controller",
            [](const ControllerDataT& self) -> const ControllerSnapshotT* { return self.right_controller.get(); },
            py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const ControllerDataT& self)
             {
                 std::string left_str =
                     self.left_controller ? (self.left_controller->is_valid ? "valid" : "invalid") : "None";
                 std::string right_str =
                     self.right_controller ? (self.right_controller->is_valid ? "valid" : "invalid") : "None";
                 return "ControllerData(left=" + left_str + ", right=" + right_str + ")";
             });
}

} // namespace core
