// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// Adapted by X. Tian JP Tech. Initiatives Inc. for Foottroller
// Python bindings for the Foottroller FlatBuffer schema.
// Types: FoottrollerOutput (table).

#pragma once

#include <pybind11/pybind11.h>
#include <schema/foottroller_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_Foottroller(py::module& m)
{
    // Bind FoottrollerOutput table using the native type (FoottrollerOutputT).
    py::class_<FoottrollerOutputT, std::shared_ptr<FoottrollerOutputT>>(m, "FoottrollerOutput")
        .def(py::init([]() { return std::make_shared<FoottrollerOutputT>(); }))
        .def(py::init(
                 [](float stick_x, float stick_y, float LF_heading, float LF_tilt, float RF_heading, float RF_tilt,
                    bool TS_A, bool TS_B, bool TS_C, bool TS_D)
                 {
                     auto obj = std::make_shared<FoottrollerOutputT>();
                     obj->stick_x = stick_x;
                     obj->stick_y = stick_y;
                     obj->LF_heading = LF_heading;
                     obj->LF_tilt = LF_tilt;
                     obj->RF_heading = RF_heading;
                     obj->RF_tilt = RF_tilt;
                     obj->TS_A = TS_A;
                     obj->TS_B = TS_B;
                     obj->TS_C = TS_C;
                     obj->TS_D = TS_D;

                     return obj;
                 }),
             py::arg("stick_x"), py::arg("stick_y"), py::arg("LF_heading"), py::arg("LF_tilt"), py::arg("RF_heading"),
             py::arg("RF_tilt"), py::arg("TS_A"), py::arg("TS_B"), py::arg("TS_C"), py::arg("TS_D"))
        .def_property(
            "stick_x", [](const FoottrollerOutputT& self) { return self.stick_x; },
            [](FoottrollerOutputT& self, float val) { self.stick_x = val; })
        .def_property(
            "stick_y", [](const FoottrollerOutputT& self) { return self.stick_y; },
            [](FoottrollerOutputT& self, float val) { self.stick_y = val; })
        .def_property(
            "LF_heading", [](const FoottrollerOutputT& self) { return self.LF_heading; },
            [](FoottrollerOutputT& self, float val) { self.LF_heading = val; })
        .def_property(
            "LF_tilt", [](const FoottrollerOutputT& self) { return self.LF_tilt; },
            [](FoottrollerOutputT& self, float val) { self.LF_tilt = val; })
        .def_property(
            "RF_heading", [](const FoottrollerOutputT& self) { return self.RF_heading; },
            [](FoottrollerOutputT& self, float val) { self.RF_heading = val; })
        .def_property(
            "RF_tilt", [](const FoottrollerOutputT& self) { return self.RF_tilt; },
            [](FoottrollerOutputT& self, float val) { self.RF_tilt = val; })
        .def_property(
            "TS_A", [](const FoottrollerOutputT& self) { return self.TS_A; },
            [](FoottrollerOutputT& self, bool val) { self.TS_A = val; })
        .def_property(
            "TS_B", [](const FoottrollerOutputT& self) { return self.TS_B; },
            [](FoottrollerOutputT& self, bool val) { self.TS_B = val; })
        .def_property(
            "TS_C", [](const FoottrollerOutputT& self) { return self.TS_C; },
            [](FoottrollerOutputT& self, bool val) { self.TS_C = val; })
        .def_property(
            "TS_D", [](const FoottrollerOutputT& self) { return self.TS_D; },
            [](FoottrollerOutputT& self, bool val) { self.TS_D = val; })
        .def("__repr__",
             [](const FoottrollerOutputT& output)
             {
                 std::string result = "FoottrollerOutput(stick_x=" + std::to_string(output.stick_x);
                 result += ", stick_y=" + std::to_string(output.stick_y);
                 result += ", LF_heading=" + std::to_string(output.LF_heading);
                 result += ", LF_tilt=" + std::to_string(output.LF_tilt);
                 result += ", RF_heading=" + std::to_string(output.RF_heading);
                 result += ", RF_tilt=" + std::to_string(output.RF_tilt);
                 result += ", TS_A=" + std::to_string(output.TS_A);
                 result += ", TS_B=" + std::to_string(output.TS_B);
                 result += ", TS_C=" + std::to_string(output.TS_C);
                 result += ", TS_D=" + std::to_string(output.TS_D);
                 result += ")";
                 return result;
             });

    py::class_<FoottrollerOutputRecordT, std::shared_ptr<FoottrollerOutputRecordT>>(m, "FoottrollerOutputRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const FoottrollerOutputT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<FoottrollerOutputRecordT>();
                     obj->data = std::make_shared<FoottrollerOutputT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly(
            "data", [](const FoottrollerOutputRecordT& self) -> std::shared_ptr<FoottrollerOutputT> { return self.data; })
        .def_readonly("timestamp", &FoottrollerOutputRecordT::timestamp)
        .def("__repr__",
             [](const FoottrollerOutputRecordT& self) {
                 return "FoottrollerOutputRecord(data=" + std::string(self.data ? "FoottrollerOutput(...)" : "None") +
                        ")";
             });

    py::class_<FoottrollerOutputTrackedT, std::shared_ptr<FoottrollerOutputTrackedT>>(m, "FoottrollerOutputTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const FoottrollerOutputT& data)
                 {
                     auto obj = std::make_shared<FoottrollerOutputTrackedT>();
                     obj->data = std::make_shared<FoottrollerOutputT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly("data",
                               [](const FoottrollerOutputTrackedT& self) -> std::shared_ptr<FoottrollerOutputT>
                               { return self.data; })
        .def("__repr__",
             [](const FoottrollerOutputTrackedT& self) {
                 return std::string("FoottrollerOutputTrackedT(data=") +
                        (self.data ? "FoottrollerOutput(...)" : "None") + ")";
             });
}

} // namespace core
