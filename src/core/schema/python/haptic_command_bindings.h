// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the vendor-neutral HapticCommand FlatBuffer schema.
// Only HapticCommand is bound: this schema's Record wrapper exists to satisfy the
// SchemaTracker<RecordT, DataTableT> template, and the tracker is push-direction with
// recording disabled, so nothing ever hands one to Python.
//
// The constructor is the only producer-side entry point: it encodes, so the command
// a caller builds is already the wire payload HapticCommandPushTracker.push() carries
// to a peer-process device plugin.

#pragma once

#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/haptic_command_generated.h>

#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_haptic_command(py::module& m)
{
    serialized_class<HapticCommand>(m, "HapticCommand", "Encoded haptic command for one named actuator endpoint.")
        .def(py::init(
                 [](const std::string& endpoint, const std::vector<float>& values)
                 {
                     HapticCommandT native;
                     native.endpoint = endpoint;
                     native.values = values;
                     return pack<HapticCommand>(native);
                 }),
             py::arg("endpoint") = std::string{}, py::arg("values") = std::vector<float>{}, "Encode a haptic command.")
        .def_property_readonly("endpoint", string_field(&HapticCommand::endpoint))
        .def_property_readonly("values", vector_field(&HapticCommand::values));
}

} // namespace core
