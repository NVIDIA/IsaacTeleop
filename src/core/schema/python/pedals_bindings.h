// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Pedals FlatBuffer schema.
// Types: Generic3AxisPedalOutput (table).

#pragma once

#include <pybind11/pybind11.h>
#include <schema/pedals_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_pedals(py::module& m)
{
    // Bind Generic3AxisPedalOutput table using the native type (Generic3AxisPedalOutputT).
    py::class_<Generic3AxisPedalOutputT>(m, "Generic3AxisPedalOutput")
        .def(py::init<>())
        .def_readwrite("is_valid", &Generic3AxisPedalOutputT::is_valid)
        .def_property(
            "timestamp", [](const Generic3AxisPedalOutputT& self) -> const Timestamp* { return self.timestamp.get(); },
            [](Generic3AxisPedalOutputT& self, const Timestamp& ts) { self.timestamp = std::make_unique<Timestamp>(ts); })
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
                 std::string result =
                     "Generic3AxisPedalOutput(is_valid=" + std::string(output.is_valid ? "True" : "False");
                 if (output.timestamp)
                 {
                     result += ", timestamp=Timestamp(device_time=" + std::to_string(output.timestamp->device_time()) +
                               ", common_time=" + std::to_string(output.timestamp->common_time()) + ")";
                 }
                 else
                 {
                     result += ", timestamp=None";
                 }
                 result += ", left_pedal=" + std::to_string(output.left_pedal);
                 result += ", right_pedal=" + std::to_string(output.right_pedal);
                 result += ", rudder=" + std::to_string(output.rudder);
                 result += ")";
                 return result;
             });
}

} // namespace core
