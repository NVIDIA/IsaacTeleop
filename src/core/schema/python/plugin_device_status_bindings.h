// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/plugin_device_status_generated.h>

#include <cstdint>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_plugin_device_status(py::module& m)
{
    py::enum_<PluginDeviceState>(m, "PluginDeviceState")
        .value("UNKNOWN", PluginDeviceState_UNKNOWN)
        .value("CONNECTED", PluginDeviceState_CONNECTED)
        .value("DISCONNECTED", PluginDeviceState_DISCONNECTED)
        .value("DEGRADED", PluginDeviceState_DEGRADED)
        .value("FAILED", PluginDeviceState_FAILED)
        .value("DISABLED", PluginDeviceState_DISABLED);

    py::enum_<PluginDeviceReason>(m, "PluginDeviceReason")
        .value("NONE", PluginDeviceReason_NONE)
        .value("NO_HARDWARE_SIGNAL", PluginDeviceReason_NO_HARDWARE_SIGNAL)
        .value("HARDWARE_CONNECTED", PluginDeviceReason_HARDWARE_CONNECTED)
        .value("HARDWARE_DISCONNECTED", PluginDeviceReason_HARDWARE_DISCONNECTED)
        .value("RECOVERING", PluginDeviceReason_RECOVERING)
        .value("PARTIAL_FUNCTIONALITY", PluginDeviceReason_PARTIAL_FUNCTIONALITY)
        .value("DEVICE_ERROR", PluginDeviceReason_DEVICE_ERROR)
        .value("DISABLED_BY_CONFIGURATION", PluginDeviceReason_DISABLED_BY_CONFIGURATION);

    serialized_class<PluginDeviceStatus>(m, "PluginDeviceStatus", "Encoded status for one plugin-owned device.")
        .def(py::init(
                 [](const std::string& path, PluginDeviceState state, PluginDeviceReason reason, const std::string& error)
                 {
                     PluginDeviceStatusT native;
                     native.path = path;
                     native.state = state;
                     native.reason = reason;
                     native.error = error;
                     return pack<PluginDeviceStatus>(native);
                 }),
             py::arg("path") = std::string{}, py::arg("state") = PluginDeviceState_UNKNOWN,
             py::arg("reason") = PluginDeviceReason_NONE, py::arg("error") = std::string{},
             "Encode one plugin device status.")
        .def_property_readonly("path", string_field(&PluginDeviceStatus::path))
        .def_property_readonly("state", field(&PluginDeviceStatus::state))
        .def_property_readonly("reason", field(&PluginDeviceStatus::reason))
        .def_property_readonly("error", string_field(&PluginDeviceStatus::error));

    serialized_class<PluginDeviceStatusSnapshot>(
        m, "PluginDeviceStatusSnapshot", "Encoded monitoring snapshot for all devices owned by one plugin.")
        .def(py::init(
                 [](uint32_t schema_version, int64_t report_time_ns,
                    const std::vector<Serialized<PluginDeviceStatus>>& devices)
                 {
                     PluginDeviceStatusSnapshotT native;
                     native.schema_version = schema_version;
                     native.report_time_ns = report_time_ns;
                     native.devices = to_native_vector(devices, "devices");
                     return pack<PluginDeviceStatusSnapshot>(native);
                 }),
             py::arg("schema_version") = 0, py::arg("report_time_ns") = 0,
             py::arg("devices") = std::vector<Serialized<PluginDeviceStatus>>{}, "Encode a plugin device snapshot.")
        .def_property_readonly("schema_version", field(&PluginDeviceStatusSnapshot::schema_version))
        .def_property_readonly("report_time_ns", field(&PluginDeviceStatusSnapshot::report_time_ns))
        .def_property_readonly("devices", [](const Serialized<PluginDeviceStatusSnapshot>& self)
                               { return narrow_vector(self, self->devices()); });

    bind_record<PluginDeviceStatusSnapshotRecord, PluginDeviceStatusSnapshot>(
        m, "PluginDeviceStatusSnapshotRecord", "PluginDeviceStatusSnapshot");
}

} // namespace core
