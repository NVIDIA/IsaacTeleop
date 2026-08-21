// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Controller FlatBuffer schema.
// ControllerInputState, ControllerPose are structs.
// ControllerSnapshot is a table, exposed as an encoded view.

#pragma once

#include "pose_bindings.h"
#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/controller_generated.h>

#include <memory>
#include <string>

namespace py = pybind11;

namespace core
{

inline void bind_controller(py::module& m)
{
    // Bind ControllerInputState struct
    py::class_<ControllerInputState>(m, "ControllerInputState")
        .def(py::init<>())
        .def(py::init<bool, bool, bool, bool, float, float, float, float>(), py::arg("primary_click"),
             py::arg("secondary_click"), py::arg("thumbstick_click"), py::arg("menu_click"), py::arg("thumbstick_x"),
             py::arg("thumbstick_y"), py::arg("squeeze_value"), py::arg("trigger_value"))
        .def_property_readonly("primary_click", &ControllerInputState::primary_click)
        .def_property_readonly("secondary_click", &ControllerInputState::secondary_click)
        .def_property_readonly("thumbstick_click", &ControllerInputState::thumbstick_click)
        .def_property_readonly("menu_click", &ControllerInputState::menu_click)
        .def_property_readonly("thumbstick_x", &ControllerInputState::thumbstick_x)
        .def_property_readonly("thumbstick_y", &ControllerInputState::thumbstick_y)
        .def_property_readonly("squeeze_value", &ControllerInputState::squeeze_value)
        .def_property_readonly("trigger_value", &ControllerInputState::trigger_value)
        .def("__repr__",
             [](const ControllerInputState& self)
             {
                 return "ControllerInputState(primary=" + std::string(self.primary_click() ? "True" : "False") +
                        ", secondary=" + std::string(self.secondary_click() ? "True" : "False") +
                        ", menu=" + std::string(self.menu_click() ? "True" : "False") + ", thumbstick=(" +
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
                 return "ControllerPose(pose=" + pose_repr(self.pose()) +
                        ", is_valid=" + (self.is_valid() ? "True" : "False") + ")";
             });

    serialized_class<ControllerSnapshot>(
        m, "ControllerSnapshot", "Encoded controller snapshot: grip and aim poses plus the input state.")
        .def(py::init(
                 [](const ControllerPose& grip_pose, const ControllerPose& aim_pose, const ControllerInputState& inputs)
                 {
                     ControllerSnapshotT native;
                     native.grip_pose = std::make_shared<ControllerPose>(grip_pose);
                     native.aim_pose = std::make_shared<ControllerPose>(aim_pose);
                     native.inputs = std::make_shared<ControllerInputState>(inputs);
                     return pack<ControllerSnapshot>(native);
                 }),
             py::arg("grip_pose") = ControllerPose(), py::arg("aim_pose") = ControllerPose(),
             py::arg("inputs") = ControllerInputState(),
             "Encode a controller snapshot. Omitted poses are all-zero and not valid.")
        .def_property_readonly(
            "grip_pose", field(&ControllerSnapshot::grip_pose), py::return_value_policy::reference_internal)
        .def_property_readonly(
            "aim_pose", field(&ControllerSnapshot::aim_pose), py::return_value_policy::reference_internal)
        .def_property_readonly("inputs", field(&ControllerSnapshot::inputs), py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const Serialized<ControllerSnapshot>& self)
             {
                 auto pose_str = [](const ControllerPose* pose)
                 {
                     return pose != nullptr ?
                                "ControllerPose(is_valid=" + std::string(pose->is_valid() ? "True" : "False") + ")" :
                                std::string("None");
                 };
                 return "ControllerSnapshot(grip_pose=" + pose_str(self->grip_pose()) +
                        ", aim_pose=" + pose_str(self->aim_pose()) + ")";
             });

    bind_record<ControllerSnapshotRecord, ControllerSnapshot>(m, "ControllerSnapshotRecord", "ControllerSnapshot");
}

} // namespace core
