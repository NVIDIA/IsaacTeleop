// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the VehicleControl FlatBuffer schema.

#pragma once

#include <pybind11/pybind11.h>
#include <schema/timestamp_generated.h>
#include <schema/vehicle_control_generated.h>

#include <cstdint>
#include <memory>
#include <string>

namespace py = pybind11;

namespace core
{

inline void bind_vehicle_control(py::module& m)
{
    py::class_<VehicleControlCommandT, std::shared_ptr<VehicleControlCommandT>>(m, "VehicleControlCommand")
        .def(py::init([]() { return std::make_shared<VehicleControlCommandT>(); }))
        .def(py::init(
                 [](uint64_t sequence, float steer, float accel, float throttle, float brake)
                 {
                     auto obj = std::make_shared<VehicleControlCommandT>();
                     obj->sequence = sequence;
                     obj->steer = steer;
                     obj->accel = accel;
                     obj->throttle = throttle;
                     obj->brake = brake;
                     return obj;
                 }),
             py::arg("sequence"), py::arg("steer"), py::arg("accel"), py::arg("throttle"), py::arg("brake"))
        .def_readwrite("sequence", &VehicleControlCommandT::sequence)
        .def_readwrite("steer", &VehicleControlCommandT::steer)
        .def_readwrite("accel", &VehicleControlCommandT::accel)
        .def_readwrite("throttle", &VehicleControlCommandT::throttle)
        .def_readwrite("brake", &VehicleControlCommandT::brake)
        .def("__repr__",
             [](const VehicleControlCommandT& command)
             {
                 return "VehicleControlCommand(sequence=" + std::to_string(command.sequence) +
                        ", steer=" + std::to_string(command.steer) + ", accel=" + std::to_string(command.accel) +
                        ", throttle=" + std::to_string(command.throttle) + ", brake=" + std::to_string(command.brake) +
                        ")";
             });

    py::class_<VehicleControlCommandRecordT, std::shared_ptr<VehicleControlCommandRecordT>>(
        m, "VehicleControlCommandRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const VehicleControlCommandT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<VehicleControlCommandRecordT>();
                     obj->data = std::make_shared<VehicleControlCommandT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly("data",
                               [](const VehicleControlCommandRecordT& self) -> std::shared_ptr<VehicleControlCommandT>
                               { return self.data; })
        .def_readonly("timestamp", &VehicleControlCommandRecordT::timestamp);
}

} // namespace core
