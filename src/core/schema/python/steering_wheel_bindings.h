// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the SteeringWheel FlatBuffer schema.

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/steering_wheel_generated.h>
#include <schema/timestamp_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_steering_wheel(py::module& m)
{
    py::class_<SteeringWheelOutputT, std::shared_ptr<SteeringWheelOutputT>>(m, "SteeringWheelOutput")
        .def(py::init([]() { return std::make_shared<SteeringWheelOutputT>(); }))
        .def(py::init(
                 [](float steering, float throttle, float brake, float clutch, std::vector<uint8_t> buttons, int hat_x,
                    int hat_y)
                 {
                     auto obj = std::make_shared<SteeringWheelOutputT>();
                     obj->steering = steering;
                     obj->throttle = throttle;
                     obj->brake = brake;
                     obj->clutch = clutch;
                     obj->buttons = std::move(buttons);
                     obj->hat_x = hat_x;
                     obj->hat_y = hat_y;
                     return obj;
                 }),
             py::arg("steering"), py::arg("throttle"), py::arg("brake"), py::arg("clutch"),
             py::arg("buttons") = std::vector<uint8_t>{}, py::arg("hat_x") = 0, py::arg("hat_y") = 0)
        .def_readwrite("steering", &SteeringWheelOutputT::steering)
        .def_readwrite("throttle", &SteeringWheelOutputT::throttle)
        .def_readwrite("brake", &SteeringWheelOutputT::brake)
        .def_readwrite("clutch", &SteeringWheelOutputT::clutch)
        .def_readwrite("buttons", &SteeringWheelOutputT::buttons)
        .def_readwrite("hat_x", &SteeringWheelOutputT::hat_x)
        .def_readwrite("hat_y", &SteeringWheelOutputT::hat_y)
        .def("__repr__",
             [](const SteeringWheelOutputT& output)
             {
                 return "SteeringWheelOutput(steering=" + std::to_string(output.steering) +
                        ", throttle=" + std::to_string(output.throttle) + ", brake=" + std::to_string(output.brake) +
                        ", clutch=" + std::to_string(output.clutch) +
                        ", buttons=" + std::to_string(output.buttons.size()) +
                        ", hat_x=" + std::to_string(output.hat_x) + ", hat_y=" + std::to_string(output.hat_y) + ")";
             });

    py::class_<SteeringWheelOutputRecordT, std::shared_ptr<SteeringWheelOutputRecordT>>(m, "SteeringWheelOutputRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const SteeringWheelOutputT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<SteeringWheelOutputRecordT>();
                     obj->data = std::make_shared<SteeringWheelOutputT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly("data",
                               [](const SteeringWheelOutputRecordT& self) -> std::shared_ptr<SteeringWheelOutputT>
                               { return self.data; })
        .def_readonly("timestamp", &SteeringWheelOutputRecordT::timestamp);

    py::class_<SteeringWheelOutputTrackedT, std::shared_ptr<SteeringWheelOutputTrackedT>>(m, "SteeringWheelOutputTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const SteeringWheelOutputT& data)
                 {
                     auto obj = std::make_shared<SteeringWheelOutputTrackedT>();
                     obj->data = std::make_shared<SteeringWheelOutputT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly("data",
                               [](const SteeringWheelOutputTrackedT& self) -> std::shared_ptr<SteeringWheelOutputT>
                               { return self.data; });
}

} // namespace core
