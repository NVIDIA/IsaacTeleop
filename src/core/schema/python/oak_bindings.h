// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the OAK FlatBuffer schema.
// Types: FrameMetadata (struct with timestamp and sequence_number).

#pragma once

#include <pybind11/pybind11.h>
#include <schema/oak_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_oak(py::module& m)
{
    // Bind FrameMetadata struct.
    py::class_<FrameMetadata>(m, "FrameMetadata")
        .def(py::init<>())
        .def_property_readonly(
            "timestamp", [](const FrameMetadata& self) -> const Timestamp& { return self.timestamp(); },
            py::return_value_policy::reference_internal, "Get the dual timestamp (device and common time)")
        .def_property_readonly("sequence_number", &FrameMetadata::sequence_number, "Get the frame sequence number")
        .def("__repr__",
             [](const FrameMetadata& metadata)
             {
                 return "FrameMetadata(timestamp=Timestamp(device_time=" +
                        std::to_string(metadata.timestamp().device_time()) +
                        ", common_time=" + std::to_string(metadata.timestamp().common_time()) + ")" +
                        ", sequence_number=" + std::to_string(metadata.sequence_number()) + ")";
             });
}

} // namespace core
