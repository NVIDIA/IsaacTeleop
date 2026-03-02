// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Timestamp FlatBuffer schema.
// Types: DeviceDataTimestamp (struct).

#pragma once

#include <pybind11/pybind11.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_timestamp(py::module& m)
{
    py::class_<DeviceDataTimestamp, std::shared_ptr<DeviceDataTimestamp>>(
        m, "DeviceDataTimestamp",
        "Timestamps for a single device data sample.\n\n"
        "All _local_common_clock fields are in system monotonic nanoseconds\n"
        "(CLOCK_MONOTONIC on Linux, QueryPerformanceCounter-derived on Windows).\n"
        "Values from different sources are directly comparable.\n\n"
        "sample_time_raw_device_clock is the source device's own clock in nanoseconds\n"
        "and is NOT comparable across devices.")
        .def(py::init<>())
        .def(py::init<int64_t, int64_t, int64_t>(), py::arg("available_time_local_common_clock"),
             py::arg("sample_time_local_common_clock"), py::arg("sample_time_raw_device_clock"))
        .def_property_readonly("available_time_local_common_clock",
                               &DeviceDataTimestamp::available_time_local_common_clock,
                               "When the sample became available to the local system, in system monotonic "
                               "nanoseconds. Use this as the MCAP log timestamp. Latency = available - sample.")
        .def_property_readonly("sample_time_local_common_clock", &DeviceDataTimestamp::sample_time_local_common_clock,
                               "When the sample was captured, expressed in system monotonic nanoseconds. "
                               "Comparable across all data sources on the same machine.")
        .def_property_readonly("sample_time_raw_device_clock", &DeviceDataTimestamp::sample_time_raw_device_clock,
                               "When the sample was captured according to the source device's own clock "
                               "(nanoseconds). Not comparable across different devices.")
        .def("__repr__",
             [](const DeviceDataTimestamp& self)
             {
                 return "DeviceDataTimestamp(available=" + std::to_string(self.available_time_local_common_clock()) +
                        ", sample_local=" + std::to_string(self.sample_time_local_common_clock()) +
                        ", sample_raw=" + std::to_string(self.sample_time_raw_device_clock()) + ")";
             });
}

} // namespace core
