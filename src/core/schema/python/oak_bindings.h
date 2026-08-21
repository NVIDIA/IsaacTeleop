// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the OAK FlatBuffer schema.
// Types: StreamType (enum), FrameMetadataOak (table), exposed as an encoded view.

#pragma once

#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <schema/oak_generated.h>

#include <cstdint>
#include <string>

namespace py = pybind11;

namespace core
{

inline void bind_oak(py::module& m)
{
    py::enum_<StreamType>(m, "StreamType")
        .value("Color", StreamType_Color)
        .value("MonoLeft", StreamType_MonoLeft)
        .value("MonoRight", StreamType_MonoRight);

    serialized_class<FrameMetadataOak>(m, "FrameMetadataOak", "Encoded per-frame OAK camera metadata.")
        .def(py::init(
                 [](StreamType stream, uint64_t sequence_number)
                 {
                     FrameMetadataOakT native;
                     native.stream = stream;
                     native.sequence_number = sequence_number;
                     return pack<FrameMetadataOak>(native);
                 }),
             py::arg("stream") = StreamType_Color, py::arg("sequence_number") = 0,
             "Encode frame metadata. Defaults to stream Color at sequence number 0.")
        .def_property_readonly("stream", field(&FrameMetadataOak::stream), "The stream type that produced this frame")
        .def_property_readonly(
            "sequence_number", field(&FrameMetadataOak::sequence_number), "The per-stream sequence number")
        .def("__repr__",
             [](const Serialized<FrameMetadataOak>& self)
             {
                 return "FrameMetadataOak(stream=" + std::string(EnumNameStreamType(self->stream())) +
                        ", sequence_number=" + std::to_string(self->sequence_number()) + ")";
             });

    bind_record<FrameMetadataOakRecord, FrameMetadataOak>(m, "FrameMetadataOakRecord", "FrameMetadataOak");
}

} // namespace core
