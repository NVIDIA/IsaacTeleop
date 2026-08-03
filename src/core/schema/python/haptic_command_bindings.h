// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the vendor-neutral HapticCommand FlatBuffer schema.
// Types: HapticCommand (table) and HapticCommandRecord, plus a pack helper that
// serialises a command to the bytes a TensorPushTracker pushes to a peer-process
// device plugin.

#pragma once

#include "schema_serialized.h"

#include <flatbuffers/flatbuffers.h>
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
        .def_property_readonly("endpoint",
                               [](const Serialized<HapticCommand>& self)
                               {
                                   const auto* endpoint = self ? self->endpoint() : nullptr;
                                   return endpoint != nullptr ? endpoint->str() : std::string{};
                               })
        .def_property_readonly("values",
                               [](const Serialized<HapticCommand>& self)
                               {
                                   // FlatBuffers omits an empty vector rather than encoding a
                                   // zero-length one, so an absent field is "no values".
                                   const auto* values = self ? self->values() : nullptr;
                                   return values != nullptr ? std::vector<float>(values->begin(), values->end()) :
                                                              std::vector<float>{};
                               });

    bind_record<HapticCommandRecord, HapticCommand>(m, "HapticCommandRecord", "HapticCommand");

    // Producer-side encode: serialise a HapticCommand (endpoint + values) to the raw
    // FlatBuffer bytes that TensorPushTracker.push() carries to the consumer. Distinct
    // from the HapticCommand constructor, which yields a view rather than the wire bytes.
    m.def(
        "pack_haptic_command",
        [](const std::string& endpoint, const std::vector<float>& values) -> py::bytes
        {
            HapticCommandT cmd;
            cmd.endpoint = endpoint;
            cmd.values = values;
            flatbuffers::FlatBufferBuilder fbb;
            fbb.Finish(HapticCommand::Pack(fbb, &cmd));
            return py::bytes(reinterpret_cast<const char*>(fbb.GetBufferPointer()), fbb.GetSize());
        },
        py::arg("endpoint"), py::arg("values"),
        "Serialise a HapticCommand (endpoint, values) to FlatBuffer bytes for TensorPushTracker.push().");
}

} // namespace core
