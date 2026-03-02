// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the OAK FlatBuffer schema.
// Types: StreamType (enum), FrameMetadataOak (table).

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/oak_generated.h>
#include <schema/timestamp_generated.h>

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

    py::class_<FrameMetadataOakT, std::shared_ptr<FrameMetadataOakT>>(m, "FrameMetadataOak")
        .def(py::init([]() { return std::make_shared<FrameMetadataOakT>(); }))
        .def(py::init(
                 [](StreamType stream, uint64_t sequence_number)
                 {
                     auto obj = std::make_shared<FrameMetadataOakT>();
                     obj->stream = stream;
                     obj->sequence_number = sequence_number;
                     return obj;
                 }),
             py::arg("stream"), py::arg("sequence_number"))
        .def_property(
            "stream", [](const FrameMetadataOakT& self) { return self.stream; },
            [](FrameMetadataOakT& self, StreamType val) { self.stream = val; },
            "Get or set the stream type that produced this frame")
        .def_readwrite("sequence_number", &FrameMetadataOakT::sequence_number, "Get or set the per-stream sequence number")
        .def("__repr__",
             [](const FrameMetadataOakT& metadata)
             {
                 return "FrameMetadataOak(stream=" + std::string(EnumNameStreamType(metadata.stream)) +
                        ", sequence_number=" + std::to_string(metadata.sequence_number) + ")";
             });

    py::class_<FrameMetadataOakRecordT, std::shared_ptr<FrameMetadataOakRecordT>>(m, "FrameMetadataOakRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const FrameMetadataOakT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<FrameMetadataOakRecordT>();
                     obj->data = std::make_shared<FrameMetadataOakT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly(
            "data", [](const FrameMetadataOakRecordT& self) -> std::shared_ptr<FrameMetadataOakT> { return self.data; })
        .def_readonly("timestamp", &FrameMetadataOakRecordT::timestamp)
        .def("__repr__", [](const FrameMetadataOakRecordT& self)
             { return "FrameMetadataOakRecord(data=" + std::string(self.data ? "FrameMetadataOak(...)" : "None") + ")"; });

    py::class_<FrameMetadataOakTrackedT, std::shared_ptr<FrameMetadataOakTrackedT>>(m, "FrameMetadataOakTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const FrameMetadataOakT& data)
                 {
                     auto obj = std::make_shared<FrameMetadataOakTrackedT>();
                     obj->data = std::make_shared<FrameMetadataOakT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly(
            "data", [](const FrameMetadataOakTrackedT& self) -> std::shared_ptr<FrameMetadataOakT> { return self.data; })
        .def("__repr__",
             [](const FrameMetadataOakTrackedT& self) {
                 return std::string("FrameMetadataOakTrackedT(data=") + (self.data ? "FrameMetadataOak(...)" : "None") +
                        ")";
             });
}

} // namespace core
