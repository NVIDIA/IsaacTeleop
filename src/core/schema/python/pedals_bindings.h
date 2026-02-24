// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Pedals FlatBuffer schema.
// Types: Generic3AxisPedalOutput (struct).

#pragma once

#include <pybind11/pybind11.h>
#include <schema/pedals_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_pedals(py::module& m)
{
    // Bind Generic3AxisPedalOutput struct.
    py::class_<Generic3AxisPedalOutput>(m, "Generic3AxisPedalOutput")
        .def(py::init<>())
        .def_property_readonly("is_active", &Generic3AxisPedalOutput::is_active)
        .def_property_readonly(
            "timestamp", [](const Generic3AxisPedalOutput& self) -> const Timestamp& { return self.timestamp(); },
            py::return_value_policy::reference_internal)
        .def_property_readonly("left_pedal", &Generic3AxisPedalOutput::left_pedal)
        .def_property_readonly("right_pedal", &Generic3AxisPedalOutput::right_pedal)
        .def_property_readonly("rudder", &Generic3AxisPedalOutput::rudder)
        .def("__repr__",
             [](const Generic3AxisPedalOutput& output)
             {
                 return "Generic3AxisPedalOutput(is_active=" + std::string(output.is_active() ? "True" : "False") +
                        ", timestamp=Timestamp(device_time=" + std::to_string(output.timestamp().device_time()) +
                        ", common_time=" + std::to_string(output.timestamp().common_time()) + ")" +
                        ", left_pedal=" + std::to_string(output.left_pedal()) +
                        ", right_pedal=" + std::to_string(output.right_pedal()) +
                        ", rudder=" + std::to_string(output.rudder()) + ")";
             });
}

} // namespace core
