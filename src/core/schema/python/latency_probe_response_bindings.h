// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pybind11/pybind11.h>
#include <schema/latency_probe_response_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_latency_probe_response(py::module& m)
{
    py::class_<LatencyProbeResponseT, std::shared_ptr<LatencyProbeResponseT>>(m, "LatencyProbeResponse")
        .def(py::init([]() { return std::make_shared<LatencyProbeResponseT>(); }))
        .def(py::init(
                 [](uint32_t sequence, float value)
                 {
                     auto obj = std::make_shared<LatencyProbeResponseT>();
                     obj->sequence = sequence;
                     obj->value = value;
                     return obj;
                 }),
             py::arg("sequence"), py::arg("value"))
        .def_readwrite("sequence", &LatencyProbeResponseT::sequence)
        .def_readwrite("value", &LatencyProbeResponseT::value);

    py::class_<LatencyProbeResponseTrackedT, std::shared_ptr<LatencyProbeResponseTrackedT>>(
        m, "LatencyProbeResponseTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const LatencyProbeResponseT& data)
                 {
                     auto obj = std::make_shared<LatencyProbeResponseTrackedT>();
                     obj->data = std::make_shared<LatencyProbeResponseT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly("data",
                               [](const LatencyProbeResponseTrackedT& self) -> std::shared_ptr<LatencyProbeResponseT>
                               { return self.data; });

    py::class_<LatencyProbeResponseRecordT, std::shared_ptr<LatencyProbeResponseRecordT>>(m, "LatencyProbeResponseRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const LatencyProbeResponseT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<LatencyProbeResponseRecordT>();
                     obj->data = std::make_shared<LatencyProbeResponseT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly("data",
                               [](const LatencyProbeResponseRecordT& self) -> std::shared_ptr<LatencyProbeResponseT>
                               { return self.data; })
        .def_readonly("timestamp", &LatencyProbeResponseRecordT::timestamp)
        .def("__repr__",
             [](const LatencyProbeResponseRecordT& self) {
                 return "LatencyProbeResponseRecord(data=" +
                        std::string(self.data ? "LatencyProbeResponse(...)" : "None") + ")";
             });
}

} // namespace core
