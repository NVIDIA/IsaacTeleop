// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the SpaceMouse FlatBuffer schema.
// Types: SpaceMouseOutput (table).

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/spacemouse_generated.h>
#include <schema/timestamp_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_spacemouse(py::module& m)
{
    py::class_<SpaceMouseOutputT, std::shared_ptr<SpaceMouseOutputT>>(m, "SpaceMouseOutput")
        .def(py::init([]() { return std::make_shared<SpaceMouseOutputT>(); }))
        .def(py::init(
                 [](std::vector<float> translation, std::vector<float> rotation, std::vector<uint16_t> pressed_buttons,
                    bool is_valid)
                 {
                     auto obj = std::make_shared<SpaceMouseOutputT>();
                     obj->translation = std::move(translation);
                     obj->rotation = std::move(rotation);
                     obj->pressed_buttons = std::move(pressed_buttons);
                     obj->is_valid = is_valid;
                     return obj;
                 }),
             py::arg("translation"), py::arg("rotation"), py::arg("pressed_buttons"), py::arg("is_valid"))
        .def_property(
            "translation", [](const SpaceMouseOutputT& self) { return self.translation; },
            [](SpaceMouseOutputT& self, std::vector<float> val) { self.translation = std::move(val); })
        .def_property(
            "rotation", [](const SpaceMouseOutputT& self) { return self.rotation; },
            [](SpaceMouseOutputT& self, std::vector<float> val) { self.rotation = std::move(val); })
        .def_property(
            "pressed_buttons", [](const SpaceMouseOutputT& self) { return self.pressed_buttons; },
            [](SpaceMouseOutputT& self, std::vector<uint16_t> val) { self.pressed_buttons = std::move(val); })
        .def_property(
            "is_valid", [](const SpaceMouseOutputT& self) { return self.is_valid; },
            [](SpaceMouseOutputT& self, bool val) { self.is_valid = val; })
        .def("__repr__",
             [](const SpaceMouseOutputT& self)
             {
                 std::string result = "SpaceMouseOutput(translation=[";
                 for (size_t i = 0; i < self.translation.size(); ++i)
                 {
                     if (i > 0)
                         result += ", ";
                     result += std::to_string(self.translation[i]);
                 }
                 result += "], rotation=[";
                 for (size_t i = 0; i < self.rotation.size(); ++i)
                 {
                     if (i > 0)
                         result += ", ";
                     result += std::to_string(self.rotation[i]);
                 }
                 result += "], pressed_buttons=[";
                 for (size_t i = 0; i < self.pressed_buttons.size(); ++i)
                 {
                     if (i > 0)
                         result += ", ";
                     result += std::to_string(self.pressed_buttons[i]);
                 }
                 result += "], is_valid=" + std::to_string(self.is_valid) + ")";
                 return result;
             });

    py::class_<SpaceMouseOutputRecordT, std::shared_ptr<SpaceMouseOutputRecordT>>(m, "SpaceMouseOutputRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const SpaceMouseOutputT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<SpaceMouseOutputRecordT>();
                     obj->data = std::make_shared<SpaceMouseOutputT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly(
            "data", [](const SpaceMouseOutputRecordT& self) -> std::shared_ptr<SpaceMouseOutputT> { return self.data; })
        .def_readonly("timestamp", &SpaceMouseOutputRecordT::timestamp)
        .def("__repr__", [](const SpaceMouseOutputRecordT& self)
             { return "SpaceMouseOutputRecord(data=" + std::string(self.data ? "SpaceMouseOutput(...)" : "None") + ")"; });

    py::class_<SpaceMouseOutputTrackedT, std::shared_ptr<SpaceMouseOutputTrackedT>>(m, "SpaceMouseOutputTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const SpaceMouseOutputT& data)
                 {
                     auto obj = std::make_shared<SpaceMouseOutputTrackedT>();
                     obj->data = std::make_shared<SpaceMouseOutputT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly(
            "data", [](const SpaceMouseOutputTrackedT& self) -> std::shared_ptr<SpaceMouseOutputT> { return self.data; })
        .def("__repr__",
             [](const SpaceMouseOutputTrackedT& self) {
                 return std::string("SpaceMouseOutputTrackedT(data=") + (self.data ? "SpaceMouseOutput(...)" : "None") +
                        ")";
             });
}

} // namespace core
