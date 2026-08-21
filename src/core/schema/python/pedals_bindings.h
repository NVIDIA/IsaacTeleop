// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Pedals FlatBuffer schema.
// Types: Generic3AxisPedalOutput (table), exposed as an encoded view.

#pragma once

#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <schema/pedals_generated.h>

#include <string>

namespace py = pybind11;

namespace core
{

inline void bind_pedals(py::module& m)
{
    serialized_class<Generic3AxisPedalOutput>(m, "Generic3AxisPedalOutput", "Encoded three-axis pedal state.")
        .def(py::init(
                 [](float left_pedal, float right_pedal, float rudder)
                 {
                     Generic3AxisPedalOutputT native;
                     native.left_pedal = left_pedal;
                     native.right_pedal = right_pedal;
                     native.rudder = rudder;
                     return pack<Generic3AxisPedalOutput>(native);
                 }),
             py::arg("left_pedal") = 0.0f, py::arg("right_pedal") = 0.0f, py::arg("rudder") = 0.0f,
             "Encode a pedal state. Omitted axes are zero.")
        .def_property_readonly("left_pedal", field(&Generic3AxisPedalOutput::left_pedal))
        .def_property_readonly("right_pedal", field(&Generic3AxisPedalOutput::right_pedal))
        .def_property_readonly("rudder", field(&Generic3AxisPedalOutput::rudder))
        .def("__repr__",
             [](const Serialized<Generic3AxisPedalOutput>& self)
             {
                 return "Generic3AxisPedalOutput(left_pedal=" + std::to_string(self->left_pedal()) +
                        ", right_pedal=" + std::to_string(self->right_pedal()) +
                        ", rudder=" + std::to_string(self->rudder()) + ")";
             });

    bind_record<Generic3AxisPedalOutputRecord, Generic3AxisPedalOutput>(
        m, "Generic3AxisPedalOutputRecord", "Generic3AxisPedalOutput");
}

} // namespace core
