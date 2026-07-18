// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the JointState FlatBuffer schema.
// Types: JointState (table), JointStateOutput (table), and the Tracked / Record wrappers.

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/joint_state_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>
#include <string>

namespace py = pybind11;

namespace core
{

inline void bind_joint_state(py::module& m)
{
    // One named DOF (name -> position [+ optional velocity/effort/valid]).
    py::class_<JointStateT, std::shared_ptr<JointStateT>>(m, "JointState")
        .def(py::init([]() { return std::make_shared<JointStateT>(); }))
        .def(py::init(
                 [](const std::string& name, float position, float velocity, float effort, bool valid)
                 {
                     auto obj = std::make_shared<JointStateT>();
                     obj->name = name;
                     obj->position = position;
                     obj->velocity = velocity;
                     obj->effort = effort;
                     obj->valid = valid;
                     return obj;
                 }),
             py::arg("name"), py::arg("position") = 0.0f, py::arg("velocity") = 0.0f, py::arg("effort") = 0.0f,
             py::arg("valid") = true)
        .def_property(
            "name", [](const JointStateT& self) { return self.name; },
            [](JointStateT& self, const std::string& val) { self.name = val; })
        .def_property(
            "position", [](const JointStateT& self) { return self.position; },
            [](JointStateT& self, float val) { self.position = val; })
        .def_property(
            "velocity", [](const JointStateT& self) { return self.velocity; },
            [](JointStateT& self, float val) { self.velocity = val; })
        .def_property(
            "effort", [](const JointStateT& self) { return self.effort; },
            [](JointStateT& self, float val) { self.effort = val; })
        .def_property(
            "valid", [](const JointStateT& self) { return self.valid; },
            [](JointStateT& self, bool val) { self.valid = val; })
        .def("__repr__", [](const JointStateT& self)
             { return "JointState(name=" + self.name + ", position=" + std::to_string(self.position) + ")"; });

    // Per-frame device state: a list of named joints plus identity / capability flags.
    py::class_<JointStateOutputT, std::shared_ptr<JointStateOutputT>>(m, "JointStateOutput")
        .def(py::init([]() { return std::make_shared<JointStateOutputT>(); }))
        .def_property(
            "joints", [](const JointStateOutputT& self) { return self.joints; },
            [](JointStateOutputT& self, std::vector<std::shared_ptr<JointStateT>> val) { self.joints = std::move(val); })
        .def_property(
            "device_id", [](const JointStateOutputT& self) { return self.device_id; },
            [](JointStateOutputT& self, const std::string& val) { self.device_id = val; })
        .def_property(
            "has_velocity", [](const JointStateOutputT& self) { return self.has_velocity; },
            [](JointStateOutputT& self, bool val) { self.has_velocity = val; })
        .def_property(
            "has_effort", [](const JointStateOutputT& self) { return self.has_effort; },
            [](JointStateOutputT& self, bool val) { self.has_effort = val; })
        .def_property(
            "ee_pose_valid", [](const JointStateOutputT& self) { return self.ee_pose_valid; },
            [](JointStateOutputT& self, bool val) { self.ee_pose_valid = val; })
        .def("__repr__",
             [](const JointStateOutputT& self) {
                 return "JointStateOutput(device_id=" + self.device_id +
                        ", joints=" + std::to_string(self.joints.size()) + ")";
             });

    py::class_<JointStateOutputRecordT, std::shared_ptr<JointStateOutputRecordT>>(m, "JointStateOutputRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const JointStateOutputT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<JointStateOutputRecordT>();
                     obj->data = std::make_shared<JointStateOutputT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly(
            "data", [](const JointStateOutputRecordT& self) -> std::shared_ptr<JointStateOutputT> { return self.data; })
        .def_readonly("timestamp", &JointStateOutputRecordT::timestamp);

    py::class_<JointStateOutputTrackedT, std::shared_ptr<JointStateOutputTrackedT>>(m, "JointStateOutputTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const JointStateOutputT& data)
                 {
                     auto obj = std::make_shared<JointStateOutputTrackedT>();
                     obj->data = std::make_shared<JointStateOutputT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly(
            "data", [](const JointStateOutputTrackedT& self) -> std::shared_ptr<JointStateOutputT> { return self.data; })
        .def("__repr__",
             [](const JointStateOutputTrackedT& self) {
                 return std::string("JointStateOutputTrackedT(data=") + (self.data ? "JointStateOutput(...)" : "None") +
                        ")";
             });
}

} // namespace core
