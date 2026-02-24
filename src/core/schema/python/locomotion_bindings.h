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
    // velocity_valid and pose_valid indicate the active mode; both velocity and pose are
    // always populated when data is non-null, but should only be consumed when the flag is true.
    py::class_<LocomotionCommandT, std::shared_ptr<LocomotionCommandT>>(m, "LocomotionCommand")
        .def(py::init(
            []()
            {
                auto obj = std::make_shared<LocomotionCommandT>();
                obj->timestamp = std::make_shared<Timestamp>();
                obj->velocity = std::make_shared<Twist>();
                obj->pose = std::make_shared<Pose>();
                obj->velocity_valid = false;
                obj->pose_valid = false;
                return obj;
            }))
        .def(py::init(
                 [](const Twist& velocity, bool velocity_valid, const Pose& pose, bool pose_valid,
                    const Timestamp& timestamp)
                 {
                     auto obj = std::make_shared<LocomotionCommandT>();
                     obj->velocity = std::make_shared<Twist>(velocity);
                     obj->velocity_valid = velocity_valid;
                     obj->pose = std::make_shared<Pose>(pose);
                     obj->pose_valid = pose_valid;
                     obj->timestamp = std::make_shared<Timestamp>(timestamp);
                     return obj;
                 }),
             py::arg("velocity"), py::arg("velocity_valid"), py::arg("pose"), py::arg("pose_valid"), py::arg("timestamp"))
        .def_property(
            "timestamp", [](const LocomotionCommandT& self) -> const Timestamp* { return self.timestamp.get(); },
            [](LocomotionCommandT& self, const Timestamp& ts) { self.timestamp = std::make_shared<Timestamp>(ts); })
        .def_property(
            "velocity", [](const LocomotionCommandT& self) -> const Twist* { return self.velocity.get(); },
            [](LocomotionCommandT& self, const Twist& vel) { self.velocity = std::make_shared<Twist>(vel); })
        .def_property(
            "pose", [](const LocomotionCommandT& self) -> const Pose* { return self.pose.get(); },
            [](LocomotionCommandT& self, const Pose& p) { self.pose = std::make_shared<Pose>(p); })
        .def_property(
            "velocity_valid", [](const LocomotionCommandT& self) { return self.velocity_valid; },
            [](LocomotionCommandT& self, bool v) { self.velocity_valid = v; })
        .def_property(
            "pose_valid", [](const LocomotionCommandT& self) { return self.pose_valid; },
            [](LocomotionCommandT& self, bool v) { self.pose_valid = v; })
        .def("__repr__",
             [](const LocomotionCommandT& cmd)
             {
                 std::string ts = cmd.timestamp ?
                                      "Timestamp(device_time=" + std::to_string(cmd.timestamp->device_time()) +
                                          ", common_time=" + std::to_string(cmd.timestamp->common_time()) + ")" :
                                      "None";
                 return "LocomotionCommand(timestamp=" + ts +
                        ", velocity_valid=" + (cmd.velocity_valid ? "True" : "False") +
                        ", pose_valid=" + (cmd.pose_valid ? "True" : "False") + ")";
             });

    py::class_<LocomotionCommandTrackedT>(m, "LocomotionCommandTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const LocomotionCommandT& data)
                 {
                     auto obj = std::make_unique<LocomotionCommandTrackedT>();
                     obj->data = std::make_shared<LocomotionCommandT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly("data",
                               [](const LocomotionCommandTrackedT& self) -> std::shared_ptr<LocomotionCommandT>
                               { return self.data; })
        .def("__repr__",
             [](const LocomotionCommandTrackedT& self) {
                 return std::string("LocomotionCommandTrackedT(data=") +
                        (self.data ? "LocomotionCommand(...)" : "None") + ")";
             });
}

} // namespace core
