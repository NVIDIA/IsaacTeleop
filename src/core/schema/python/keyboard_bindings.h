// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Keyboard FlatBuffer schema.
// Types: KeyboardOutput (table).

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/keyboard_generated.h>
#include <schema/timestamp_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_keyboard(py::module& m)
{
    py::class_<KeyboardOutputT, std::shared_ptr<KeyboardOutputT>>(m, "KeyboardOutput")
        .def(py::init([]() { return std::make_shared<KeyboardOutputT>(); }))
        .def(py::init(
                 [](std::vector<uint16_t> pressed_keys, bool is_valid)
                 {
                     auto obj = std::make_shared<KeyboardOutputT>();
                     obj->pressed_keys = std::move(pressed_keys);
                     obj->is_valid = is_valid;
                     return obj;
                 }),
             py::arg("pressed_keys"), py::arg("is_valid"))
        .def_property(
            "pressed_keys", [](const KeyboardOutputT& self) { return self.pressed_keys; },
            [](KeyboardOutputT& self, std::vector<uint16_t> val) { self.pressed_keys = std::move(val); })
        .def_property(
            "is_valid", [](const KeyboardOutputT& self) { return self.is_valid; },
            [](KeyboardOutputT& self, bool val) { self.is_valid = val; })
        .def("__repr__",
             [](const KeyboardOutputT& self)
             {
                 std::string result = "KeyboardOutput(pressed_keys=[";
                 for (size_t i = 0; i < self.pressed_keys.size(); ++i)
                 {
                     if (i > 0)
                         result += ", ";
                     result += std::to_string(self.pressed_keys[i]);
                 }
                 result += "], is_valid=" + std::to_string(self.is_valid) + ")";
                 return result;
             });

    py::class_<KeyboardOutputRecordT, std::shared_ptr<KeyboardOutputRecordT>>(m, "KeyboardOutputRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const KeyboardOutputT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<KeyboardOutputRecordT>();
                     obj->data = std::make_shared<KeyboardOutputT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly(
            "data", [](const KeyboardOutputRecordT& self) -> std::shared_ptr<KeyboardOutputT> { return self.data; })
        .def_readonly("timestamp", &KeyboardOutputRecordT::timestamp)
        .def("__repr__", [](const KeyboardOutputRecordT& self)
             { return "KeyboardOutputRecord(data=" + std::string(self.data ? "KeyboardOutput(...)" : "None") + ")"; });

    py::class_<KeyboardOutputTrackedT, std::shared_ptr<KeyboardOutputTrackedT>>(m, "KeyboardOutputTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const KeyboardOutputT& data)
                 {
                     auto obj = std::make_shared<KeyboardOutputTrackedT>();
                     obj->data = std::make_shared<KeyboardOutputT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly(
            "data", [](const KeyboardOutputTrackedT& self) -> std::shared_ptr<KeyboardOutputT> { return self.data; })
        .def("__repr__", [](const KeyboardOutputTrackedT& self)
             { return std::string("KeyboardOutputTrackedT(data=") + (self.data ? "KeyboardOutput(...)" : "None") + ")"; });
}

} // namespace core
