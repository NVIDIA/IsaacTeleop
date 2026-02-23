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
    py::class_<FrameMetadataT>(m, "FrameMetadata")
        .def(py::init<>())
        .def_property(
            "sequence_number", [](const FrameMetadataT& self) { return self.sequence_number; },
            [](FrameMetadataT& self, int val) { self.sequence_number = val; }, "Get or set the frame sequence number")
        .def("__repr__", [](const FrameMetadataT& metadata)
             { return "FrameMetadata(sequence_number=" + std::to_string(metadata.sequence_number) + ")"; });
}

} // namespace core
