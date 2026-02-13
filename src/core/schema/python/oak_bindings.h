// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the OAK FlatBuffer schema.
// Types: FrameMetadata (table with timestamp and sequence_number).

#pragma once

#include <pybind11/pybind11.h>
#include <schema/oak_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_oak(py::module& m)
{
    // Bind FrameMetadata table using the native type (FrameMetadataT).
    // This is the base metadata type for all camera frames.
    py::class_<FrameMetadataT>(m, "FrameMetadata")
        .def(py::init<>())
        .def_property(
            "timestamp", [](const FrameMetadataT& self) -> const Timestamp* { return self.timestamp.get(); },
            [](FrameMetadataT& self, const Timestamp& ts) { self.timestamp = std::make_unique<Timestamp>(ts); },
            "Get or set the dual timestamp (device and common time)")
        .def_property(
            "sequence_number", [](const FrameMetadataT& self) { return self.sequence_number; },
            [](FrameMetadataT& self, int val) { self.sequence_number = val; }, "Get or set the frame sequence number")
        .def("__repr__",
             [](const FrameMetadataT& metadata)
             {
                 std::string result = "FrameMetadata(";
                 if (metadata.timestamp)
                 {
                     result += "timestamp=Timestamp(device_time=" + std::to_string(metadata.timestamp->device_time()) +
                               ", common_time=" + std::to_string(metadata.timestamp->common_time()) + ")";
                 }
                 else
                 {
                     result += "timestamp=None";
                 }
                 result += ", sequence_number=" + std::to_string(metadata.sequence_number);
                 result += ")";
                 return result;
             });
}

} // namespace core
