// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Locomotion FlatBuffer schema.
// Types: Twist (struct), LocomotionCommand (table).

#pragma once

#include <pybind11/pybind11.h>
#include <schema/locomotion_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_locomotion(py::module& m)
{
    // Bind Twist struct (linear, angular velocities).
    py::class_<Twist>(m, "Twist")
        .def(py::init<>())
        .def(py::init<const Point&, const Point&>(), py::arg("linear"), py::arg("angular"))
        .def_property_readonly("linear", &Twist::linear)
        .def_property_readonly("angular", &Twist::angular)
        .def("__repr__",
             [](const Twist& t)
             {
                 return "Twist(linear=Point(x=" + std::to_string(t.linear().x()) +
                        ", y=" + std::to_string(t.linear().y()) + ", z=" + std::to_string(t.linear().z()) +
                        "), angular=Point(x=" + std::to_string(t.angular().x()) +
                        ", y=" + std::to_string(t.angular().y()) + ", z=" + std::to_string(t.angular().z()) + "))";
             });

    // Bind LocomotionCommand table using the native type (LocomotionCommandT).
    py::class_<LocomotionCommandT>(m, "LocomotionCommand")
        .def(py::init<>())
        .def_property(
            "timestamp", [](const LocomotionCommandT& self) -> const Timestamp* { return self.timestamp.get(); },
            [](LocomotionCommandT& self, const Timestamp& ts) { self.timestamp = std::make_unique<Timestamp>(ts); })
        .def_property(
            "velocity", [](const LocomotionCommandT& self) -> const Twist* { return self.velocity.get(); },
            [](LocomotionCommandT& self, const Twist& vel) { self.velocity = std::make_unique<Twist>(vel); })
        .def_property(
            "pose", [](const LocomotionCommandT& self) -> const Pose* { return self.pose.get(); },
            [](LocomotionCommandT& self, const Pose& p) { self.pose = std::make_unique<Pose>(p); })
        .def("__repr__",
             [](const LocomotionCommandT& cmd)
             {
                 std::string result = "LocomotionCommand(";
                 if (cmd.timestamp)
                 {
                     result += "timestamp=Timestamp(device_time=" + std::to_string(cmd.timestamp->device_time()) +
                               ", common_time=" + std::to_string(cmd.timestamp->common_time()) + ")";
                 }
                 else
                 {
                     result += "timestamp=None";
                 }
                 result += ", velocity=";
                 if (cmd.velocity)
                 {
                     result += "Twist(...)";
                 }
                 else
                 {
                     result += "None";
                 }
                 result += ", pose=";
                 if (cmd.pose)
                 {
                     result += "Pose(...)";
                 }
                 else
                 {
                     result += "None";
                 }
                 result += ")";
                 return result;
             });
}

} // namespace core
