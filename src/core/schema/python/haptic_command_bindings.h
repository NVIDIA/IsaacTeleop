// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the vendor-neutral HapticCommand FlatBuffer schema.
// Types: HapticCommand (table) + a pack helper that serialises it to the
// bytes a TensorPushTracker pushes to a peer-process device plugin.

#pragma once

#include <flatbuffers/flatbuffers.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/haptic_command_generated.h>

#include <memory>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_haptic_command(py::module& m)
{
    py::class_<HapticCommandT, std::shared_ptr<HapticCommandT>>(m, "HapticCommand")
        .def(py::init([]() { return std::make_shared<HapticCommandT>(); }))
        .def(py::init(
                 [](const std::string& endpoint, const std::vector<float>& values)
                 {
                     auto obj = std::make_shared<HapticCommandT>();
                     obj->endpoint = endpoint;
                     obj->values = values;
                     return obj;
                 }),
             py::arg("endpoint"), py::arg("values"))
        .def_property(
            "endpoint", [](const HapticCommandT& self) { return self.endpoint; },
            [](HapticCommandT& self, const std::string& v) { self.endpoint = v; })
        .def_property(
            "values", [](const HapticCommandT& self) { return self.values; },
            [](HapticCommandT& self, const std::vector<float>& v) { self.values = v; });

    // Producer-side encode: serialise a HapticCommand (endpoint + values) to
    // the FlatBuffer bytes that TensorPushTracker.push() carries to the
    // consumer. Uses the generated Pack so the wire layout always matches the
    // C++ SchemaTracker reader.
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
