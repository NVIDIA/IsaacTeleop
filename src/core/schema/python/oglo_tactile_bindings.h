// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the OGLO tactile glove FlatBuffer schema.
// Types: OgloGloveSample (table), OgloGloveSampleRecord, OgloGloveSampleTrackedT.

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/oglo_tactile_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_oglo_tactile(py::module& m)
{
    py::class_<OgloGloveSampleT, std::shared_ptr<OgloGloveSampleT>>(m, "OgloGloveSample")
        .def(py::init([]() { return std::make_shared<OgloGloveSampleT>(); }))
        .def_property(
            "seq", [](const OgloGloveSampleT& s) { return s.seq; }, [](OgloGloveSampleT& s, uint32_t v) { s.seq = v; })
        .def_property(
            "device_time_us", [](const OgloGloveSampleT& s) { return s.device_time_us; },
            [](OgloGloveSampleT& s, uint32_t v) { s.device_time_us = v; })
        .def_property(
            "taxels", [](const OgloGloveSampleT& s) { return s.taxels; },
            [](OgloGloveSampleT& s, std::vector<uint16_t> v) { s.taxels = std::move(v); },
            "80 raw 12-bit taxels (0..4095) in finger,row,col order")
        .def_property(
            "accel_x", [](const OgloGloveSampleT& s) { return s.accel_x; },
            [](OgloGloveSampleT& s, int16_t v) { s.accel_x = v; })
        .def_property(
            "accel_y", [](const OgloGloveSampleT& s) { return s.accel_y; },
            [](OgloGloveSampleT& s, int16_t v) { s.accel_y = v; })
        .def_property(
            "accel_z", [](const OgloGloveSampleT& s) { return s.accel_z; },
            [](OgloGloveSampleT& s, int16_t v) { s.accel_z = v; })
        .def_property(
            "gyro_x", [](const OgloGloveSampleT& s) { return s.gyro_x; },
            [](OgloGloveSampleT& s, int16_t v) { s.gyro_x = v; })
        .def_property(
            "gyro_y", [](const OgloGloveSampleT& s) { return s.gyro_y; },
            [](OgloGloveSampleT& s, int16_t v) { s.gyro_y = v; })
        .def_property(
            "gyro_z", [](const OgloGloveSampleT& s) { return s.gyro_z; },
            [](OgloGloveSampleT& s, int16_t v) { s.gyro_z = v; })
        .def("__repr__",
             [](const OgloGloveSampleT& s)
             {
                 return "OgloGloveSample(seq=" + std::to_string(s.seq) +
                        ", device_time_us=" + std::to_string(s.device_time_us) +
                        ", taxels=" + std::to_string(s.taxels.size()) + ")";
             });

    py::class_<OgloGloveSampleRecordT, std::shared_ptr<OgloGloveSampleRecordT>>(m, "OgloGloveSampleRecord")
        .def(py::init<>())
        .def_property_readonly(
            "data", [](const OgloGloveSampleRecordT& self) -> std::shared_ptr<OgloGloveSampleT> { return self.data; })
        .def_readonly("timestamp", &OgloGloveSampleRecordT::timestamp)
        .def("__repr__", [](const OgloGloveSampleRecordT& self)
             { return "OgloGloveSampleRecord(data=" + std::string(self.data ? "OgloGloveSample(...)" : "None") + ")"; });

    py::class_<OgloGloveSampleTrackedT, std::shared_ptr<OgloGloveSampleTrackedT>>(m, "OgloGloveSampleTrackedT")
        .def(py::init<>())
        .def_property_readonly(
            "data", [](const OgloGloveSampleTrackedT& self) -> std::shared_ptr<OgloGloveSampleT> { return self.data; })
        .def("__repr__",
             [](const OgloGloveSampleTrackedT& self) {
                 return std::string("OgloGloveSampleTrackedT(data=") + (self.data ? "OgloGloveSample(...)" : "None") +
                        ")";
             });
}

} // namespace core
