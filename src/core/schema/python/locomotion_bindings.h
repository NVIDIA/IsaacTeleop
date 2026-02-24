// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Locomotion FlatBuffer schema.
// Types: Twist (struct), LocomotionCommand (struct).

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

    // Bind LocomotionCommand struct.
    py::class_<LocomotionCommand>(m, "LocomotionCommand")
        .def(py::init<>())
        .def_property_readonly(
            "timestamp", [](const LocomotionCommand& self) -> const Timestamp& { return self.timestamp(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "velocity", [](const LocomotionCommand& self) -> const Twist& { return self.velocity(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly(
            "pose", [](const LocomotionCommand& self) -> const Pose& { return self.pose(); },
            py::return_value_policy::reference_internal)
        .def("__repr__",
             [](const LocomotionCommand& cmd)
             {
                 return "LocomotionCommand(timestamp=Timestamp(device_time=" +
                        std::to_string(cmd.timestamp().device_time()) +
                        ", common_time=" + std::to_string(cmd.timestamp().common_time()) + ")" +
                        ", velocity=Twist(...)" + ", pose=Pose(...))";
             });
}

} // namespace core
