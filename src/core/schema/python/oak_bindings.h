// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the OAK FlatBuffer schema.
// Types: StreamType (enum), FrameMetadata (table), OakMetadata (composite table).

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/oak_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_oak(py::module& m)
{
    py::enum_<StreamType>(m, "StreamType")
        .value("Color", StreamType_Color)
        .value("MonoLeft", StreamType_MonoLeft)
        .value("MonoRight", StreamType_MonoRight);

    py::class_<FrameMetadataT>(m, "FrameMetadata")
        .def(py::init<>())
        .def_property(
            "stream", [](const FrameMetadataT& self) { return self.stream; },
            [](FrameMetadataT& self, StreamType val) { self.stream = val; },
            "Get or set the stream type that produced this frame")
        .def_property(
            "timestamp", [](const FrameMetadataT& self) -> const Timestamp* { return self.timestamp.get(); },
            [](FrameMetadataT& self, const Timestamp& ts) { self.timestamp = std::make_unique<Timestamp>(ts); },
            "Get or set the dual timestamp (device and common time)")
        .def_readwrite("sequence_number", &FrameMetadataT::sequence_number, "Get or set the per-stream sequence number")
        .def("__repr__",
             [](const FrameMetadataT& metadata)
             {
                 std::string result = "FrameMetadata(stream=" + std::string(EnumNameStreamType(metadata.stream));
                 if (metadata.timestamp)
                 {
                     result += ", timestamp=Timestamp(device_time=" + std::to_string(metadata.timestamp->device_time()) +
                               ", common_time=" + std::to_string(metadata.timestamp->common_time()) + ")";
                 }
                 else
                 {
                     result += ", timestamp=None";
                 }
                 result += ", sequence_number=" + std::to_string(metadata.sequence_number) + ")";
                 return result;
             });

    py::class_<OakMetadataT>(m, "OakMetadata")
        .def(py::init<>())
        .def_property_readonly(
            "streams",
            [](const OakMetadataT& self)
            {
                std::vector<const FrameMetadataT*> out;
                out.reserve(self.streams.size());
                for (const auto& entry : self.streams)
                    out.push_back(entry.get());
                return out;
            },
            "List of per-stream FrameMetadata entries")
        .def("__repr__", [](const OakMetadataT& self)
             { return "OakMetadata(streams=" + std::to_string(self.streams.size()) + ")"; });
}

} // namespace core
