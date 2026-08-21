// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the OGLO tactile glove FlatBuffer schema.
// Types: OgloGloveSample (table) and OgloGloveSampleRecord, exposed as encoded views.

#pragma once

#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/oglo_tactile_generated.h>

#include <cstdint>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_oglo_tactile(py::module& m)
{
    serialized_class<OgloGloveSample>(m, "OgloGloveSample", "Encoded tactile glove sample.")
        .def(py::init(
                 [](uint32_t seq, uint32_t device_time_us, std::vector<uint16_t> taxels, int16_t accel_x,
                    int16_t accel_y, int16_t accel_z, int16_t gyro_x, int16_t gyro_y, int16_t gyro_z)
                 {
                     OgloGloveSampleT native;
                     native.seq = seq;
                     native.device_time_us = device_time_us;
                     native.taxels = std::move(taxels);
                     native.accel_x = accel_x;
                     native.accel_y = accel_y;
                     native.accel_z = accel_z;
                     native.gyro_x = gyro_x;
                     native.gyro_y = gyro_y;
                     native.gyro_z = gyro_z;
                     return pack<OgloGloveSample>(native);
                 }),
             py::arg("seq") = 0, py::arg("device_time_us") = 0, py::arg("taxels") = std::vector<uint16_t>{},
             py::arg("accel_x") = 0, py::arg("accel_y") = 0, py::arg("accel_z") = 0, py::arg("gyro_x") = 0,
             py::arg("gyro_y") = 0, py::arg("gyro_z") = 0, "Encode a tactile glove sample.")
        .def_property_readonly("seq", field(&OgloGloveSample::seq))
        .def_property_readonly("device_time_us", field(&OgloGloveSample::device_time_us))
        .def_property_readonly(
            "taxels", vector_field(&OgloGloveSample::taxels), "80 raw 12-bit taxels (0..4095) in finger,row,col order")
        .def_property_readonly("accel_x", field(&OgloGloveSample::accel_x))
        .def_property_readonly("accel_y", field(&OgloGloveSample::accel_y))
        .def_property_readonly("accel_z", field(&OgloGloveSample::accel_z))
        .def_property_readonly("gyro_x", field(&OgloGloveSample::gyro_x))
        .def_property_readonly("gyro_y", field(&OgloGloveSample::gyro_y))
        .def_property_readonly("gyro_z", field(&OgloGloveSample::gyro_z))
        .def("__repr__",
             [](const Serialized<OgloGloveSample>& self)
             {
                 const auto* taxels = self->taxels();
                 return "OgloGloveSample(seq=" + std::to_string(self->seq()) +
                        ", device_time_us=" + std::to_string(self->device_time_us()) +
                        ", taxels=" + std::to_string(taxels != nullptr ? taxels->size() : 0) + ")";
             });

    bind_record<OgloGloveSampleRecord, OgloGloveSample>(m, "OgloGloveSampleRecord", "OgloGloveSample");
}

} // namespace core
