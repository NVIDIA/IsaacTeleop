// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Pose FlatBuffer schema.
// All types (Point, Quaternion, Pose) are in core:: namespace.

#pragma once

#include <pybind11/pybind11.h>
#include <schema/pose_generated.h>

namespace py = pybind11;

namespace core
{

inline void bind_pose(py::module& m)
{
    // Bind Point struct (x, y, z).
    py::class_<Point>(m, "Point")
        .def(py::init<>())
        .def(py::init<float, float, float>(), py::arg("x") = 0.0f, py::arg("y") = 0.0f, py::arg("z") = 0.0f)
        .def_property_readonly("x", &Point::x)
        .def_property_readonly("y", &Point::y)
        .def_property_readonly("z", &Point::z)
        .def("__repr__",
             [](const Point& p) {
                 return "Point(x=" + std::to_string(p.x()) + ", y=" + std::to_string(p.y()) +
                        ", z=" + std::to_string(p.z()) + ")";
             });

    // Bind Quaternion struct (x, y, z, w).
    py::class_<Quaternion>(m, "Quaternion")
        .def(py::init<>())
        .def(py::init<float, float, float, float>(), py::arg("x") = 0.0f, py::arg("y") = 0.0f, py::arg("z") = 0.0f,
             py::arg("w") = 0.0f)
        .def_property_readonly("x", &Quaternion::x)
        .def_property_readonly("y", &Quaternion::y)
        .def_property_readonly("z", &Quaternion::z)
        .def_property_readonly("w", &Quaternion::w)
        .def("__repr__",
             [](const Quaternion& q)
             {
                 return "Quaternion(x=" + std::to_string(q.x()) + ", y=" + std::to_string(q.y()) +
                        ", z=" + std::to_string(q.z()) + ", w=" + std::to_string(q.w()) + ")";
             });

    // Bind Pose struct (position, orientation).
    py::class_<Pose>(m, "Pose")
        .def(py::init<>())
        .def(py::init<const Point&, const Quaternion&>(), py::arg("position"), py::arg("orientation"))
        .def_property_readonly("position", &Pose::position)
        .def_property_readonly("orientation", &Pose::orientation)
        .def("__repr__",
             [](const Pose& p)
             {
                 return "Pose(position=Point(x=" + std::to_string(p.position().x()) +
                        ", y=" + std::to_string(p.position().y()) + ", z=" + std::to_string(p.position().z()) +
                        "), orientation=Quaternion(x=" + std::to_string(p.orientation().x()) +
                        ", y=" + std::to_string(p.orientation().y()) + ", z=" + std::to_string(p.orientation().z()) +
                        ", w=" + std::to_string(p.orientation().w()) + "))";
             });
}

} // namespace core
