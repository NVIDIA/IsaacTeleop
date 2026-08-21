// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the JointState FlatBuffer schema.
// Types: JointState (table), JointStateOutput (table) and JointStateOutputRecord,
// all exposed as encoded views.

#pragma once

#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/joint_state_generated.h>

#include <memory>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_joint_state(py::module& m)
{
    // One named DOF (name -> position [+ optional velocity/effort/valid]).
    serialized_class<JointState>(m, "JointState", "Encoded state of one named joint.")
        .def(py::init(
                 [](const std::string& name, float position, float velocity, float effort, bool valid)
                 {
                     JointStateT native;
                     native.name = name;
                     native.position = position;
                     native.velocity = velocity;
                     native.effort = effort;
                     native.valid = valid;
                     return pack<JointState>(native);
                 }),
             py::arg("name"), py::arg("position") = 0.0f, py::arg("velocity") = 0.0f, py::arg("effort") = 0.0f,
             py::arg("valid") = true, "Encode one joint's state.")
        .def_property_readonly("name", string_field(&JointState::name))
        .def_property_readonly("position", field(&JointState::position))
        .def_property_readonly("velocity", field(&JointState::velocity))
        .def_property_readonly("effort", field(&JointState::effort))
        .def_property_readonly("valid", field(&JointState::valid))
        .def("__repr__",
             [](const Serialized<JointState>& self)
             {
                 const auto* name = self->name();
                 return "JointState(name=" + (name != nullptr ? name->str() : std::string{}) +
                        ", position=" + std::to_string(self->position()) + ")";
             });

    // Per-frame device state: a list of named joints plus identity / capability flags.
    serialized_class<JointStateOutput>(
        m, "JointStateOutput", "Encoded joint-space device state: named joints plus capability flags.")
        .def(py::init(
                 [](const std::vector<Serialized<JointState>>& joints, const std::string& device_id, bool has_velocity,
                    bool has_effort, const Pose* ee_pose, bool ee_pose_valid)
                 {
                     JointStateOutputT native;
                     native.joints = to_native_vector(joints, "joints");
                     native.device_id = device_id;
                     native.has_velocity = has_velocity;
                     native.has_effort = has_effort;
                     if (ee_pose != nullptr)
                     {
                         native.ee_pose = std::make_shared<Pose>(*ee_pose);
                     }
                     native.ee_pose_valid = ee_pose_valid;
                     return pack<JointStateOutput>(native);
                 }),
             py::arg("joints") = std::vector<Serialized<JointState>>{}, py::arg("device_id") = std::string{},
             py::arg("has_velocity") = false, py::arg("has_effort") = false, py::arg("ee_pose") = nullptr,
             py::arg("ee_pose_valid") = false, "Encode a joint-space device state.")
        .def_property_readonly("joints", [](const Serialized<JointStateOutput>& self)
                               { return narrow_vector(self, self ? self->joints() : nullptr); })
        .def_property_readonly("device_id", string_field(&JointStateOutput::device_id))
        .def_property_readonly("has_velocity", field(&JointStateOutput::has_velocity))
        .def_property_readonly("has_effort", field(&JointStateOutput::has_effort))
        .def_property_readonly("ee_pose", field(&JointStateOutput::ee_pose), py::return_value_policy::reference_internal)
        .def_property_readonly("ee_pose_valid", field(&JointStateOutput::ee_pose_valid))
        .def("__repr__",
             [](const Serialized<JointStateOutput>& self)
             {
                 const auto* device_id = self->device_id();
                 const auto* joints = self->joints();
                 return "JointStateOutput(device_id=" + (device_id != nullptr ? device_id->str() : std::string{}) +
                        ", joints=" + std::to_string(joints != nullptr ? joints->size() : 0) + ")";
             });

    bind_record<JointStateOutputRecord, JointStateOutput>(m, "JointStateOutputRecord", "JointStateOutput");
}

} // namespace core
