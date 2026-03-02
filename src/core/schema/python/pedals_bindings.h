// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Pedals FlatBuffer schema.
// Types: Generic3AxisPedalOutput (table).

#pragma once

#include <pybind11/pybind11.h>
#include <schema/pedals_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_pedals(py::module& m)
{
    // Bind Generic3AxisPedalOutput table using the native type (Generic3AxisPedalOutputT).
    py::class_<Generic3AxisPedalOutputT, std::shared_ptr<Generic3AxisPedalOutputT>>(m, "Generic3AxisPedalOutput")
        .def(py::init([]() { return std::make_shared<Generic3AxisPedalOutputT>(); }))
        .def(py::init(
                 [](float left_pedal, float right_pedal, float rudder)
                 {
                     auto obj = std::make_shared<Generic3AxisPedalOutputT>();
                     obj->left_pedal = left_pedal;
                     obj->right_pedal = right_pedal;
                     obj->rudder = rudder;
                     return obj;
                 }),
             py::arg("left_pedal"), py::arg("right_pedal"), py::arg("rudder"))
        .def_property(
            "left_pedal", [](const Generic3AxisPedalOutputT& self) { return self.left_pedal; },
            [](Generic3AxisPedalOutputT& self, float val) { self.left_pedal = val; })
        .def_property(
            "right_pedal", [](const Generic3AxisPedalOutputT& self) { return self.right_pedal; },
            [](Generic3AxisPedalOutputT& self, float val) { self.right_pedal = val; })
        .def_property(
            "rudder", [](const Generic3AxisPedalOutputT& self) { return self.rudder; },
            [](Generic3AxisPedalOutputT& self, float val) { self.rudder = val; })
        .def("__repr__",
             [](const Generic3AxisPedalOutputT& output)
             {
                 std::string result = "Generic3AxisPedalOutput(left_pedal=" + std::to_string(output.left_pedal);
                 result += ", right_pedal=" + std::to_string(output.right_pedal);
                 result += ", rudder=" + std::to_string(output.rudder);
                 result += ")";
                 return result;
             });

    py::class_<Generic3AxisPedalOutputRecordT, std::shared_ptr<Generic3AxisPedalOutputRecordT>>(
        m, "Generic3AxisPedalOutputRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const Generic3AxisPedalOutputT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<Generic3AxisPedalOutputRecordT>();
                     obj->data = std::make_shared<Generic3AxisPedalOutputT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly("data",
                               [](const Generic3AxisPedalOutputRecordT& self) -> std::shared_ptr<Generic3AxisPedalOutputT>
                               { return self.data; })
        .def_readonly("timestamp", &Generic3AxisPedalOutputRecordT::timestamp)
        .def("__repr__",
             [](const Generic3AxisPedalOutputRecordT& self)
             {
                 return "Generic3AxisPedalOutputRecord(data=" +
                        std::string(self.data ? "Generic3AxisPedalOutput(...)" : "None") + ")";
             });

    py::class_<Generic3AxisPedalOutputTrackedT, std::shared_ptr<Generic3AxisPedalOutputTrackedT>>(
        m, "Generic3AxisPedalOutputTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const Generic3AxisPedalOutputT& data)
                 {
                     auto obj = std::make_shared<Generic3AxisPedalOutputTrackedT>();
                     obj->data = std::make_shared<Generic3AxisPedalOutputT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly("data",
                               [](const Generic3AxisPedalOutputTrackedT& self) -> std::shared_ptr<Generic3AxisPedalOutputT>
                               { return self.data; })
        .def("__repr__",
             [](const Generic3AxisPedalOutputTrackedT& self)
             {
                 return std::string("Generic3AxisPedalOutputTrackedT(data=") +
                        (self.data ? "Generic3AxisPedalOutput(...)" : "None") + ")";
             });
}

} // namespace core
