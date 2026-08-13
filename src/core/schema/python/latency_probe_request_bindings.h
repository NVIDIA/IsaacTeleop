// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pybind11/pybind11.h>
#include <schema/latency_probe_request_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_latency_probe_request(py::module& m)
{
    py::class_<LatencyProbeRequestT, std::shared_ptr<LatencyProbeRequestT>>(m, "LatencyProbeRequest")
        .def(py::init([]() { return std::make_shared<LatencyProbeRequestT>(); }))
        .def(py::init(
                 [](uint32_t sequence, float value, uint64_t send_time_ns)
                 {
                     auto obj = std::make_shared<LatencyProbeRequestT>();
                     obj->sequence = sequence;
                     obj->value = value;
                     obj->send_time_ns = send_time_ns;
                     return obj;
                 }),
             py::arg("sequence"), py::arg("value"), py::arg("send_time_ns"))
        .def_readwrite("sequence", &LatencyProbeRequestT::sequence)
        .def_readwrite("value", &LatencyProbeRequestT::value)
        .def_readwrite("send_time_ns", &LatencyProbeRequestT::send_time_ns);

    py::class_<LatencyProbeRequestTrackedT, std::shared_ptr<LatencyProbeRequestTrackedT>>(m, "LatencyProbeRequestTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const LatencyProbeRequestT& data)
                 {
                     auto obj = std::make_shared<LatencyProbeRequestTrackedT>();
                     obj->data = std::make_shared<LatencyProbeRequestT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly("data",
                               [](const LatencyProbeRequestTrackedT& self) -> std::shared_ptr<LatencyProbeRequestT>
                               { return self.data; });

    py::class_<LatencyProbeRequestRecordT, std::shared_ptr<LatencyProbeRequestRecordT>>(m, "LatencyProbeRequestRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const LatencyProbeRequestT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<LatencyProbeRequestRecordT>();
                     obj->data = std::make_shared<LatencyProbeRequestT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly("data",
                               [](const LatencyProbeRequestRecordT& self) -> std::shared_ptr<LatencyProbeRequestT>
                               { return self.data; })
        .def_readonly("timestamp", &LatencyProbeRequestRecordT::timestamp)
        .def("__repr__",
             [](const LatencyProbeRequestRecordT& self) {
                 return "LatencyProbeRequestRecord(data=" + std::string(self.data ? "LatencyProbeRequest(...)" : "None") +
                        ")";
             });
}

} // namespace core
