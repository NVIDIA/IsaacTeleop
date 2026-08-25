// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Gamepad FlatBuffer schema.
// Types: GamepadOutput (table).

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/gamepad_generated.h>
#include <schema/timestamp_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_gamepad(py::module& m)
{
    py::class_<GamepadOutputT, std::shared_ptr<GamepadOutputT>>(m, "GamepadOutput")
        .def(py::init([]() { return std::make_shared<GamepadOutputT>(); }))
        .def(py::init(
                 [](std::vector<uint16_t> pressed_buttons, std::vector<float> axes, bool is_valid)
                 {
                     auto obj = std::make_shared<GamepadOutputT>();
                     obj->pressed_buttons = std::move(pressed_buttons);
                     obj->axes = std::move(axes);
                     obj->is_valid = is_valid;
                     return obj;
                 }),
             py::arg("pressed_buttons"), py::arg("axes"), py::arg("is_valid"))
        .def_property(
            "pressed_buttons", [](const GamepadOutputT& self) { return self.pressed_buttons; },
            [](GamepadOutputT& self, std::vector<uint16_t> val) { self.pressed_buttons = std::move(val); })
        .def_property(
            "axes", [](const GamepadOutputT& self) { return self.axes; },
            [](GamepadOutputT& self, std::vector<float> val) { self.axes = std::move(val); })
        .def_property(
            "is_valid", [](const GamepadOutputT& self) { return self.is_valid; },
            [](GamepadOutputT& self, bool val) { self.is_valid = val; })
        .def("__repr__",
             [](const GamepadOutputT& self)
             {
                 std::string result = "GamepadOutput(pressed_buttons=[";
                 for (size_t i = 0; i < self.pressed_buttons.size(); ++i)
                 {
                     if (i > 0)
                         result += ", ";
                     result += std::to_string(self.pressed_buttons[i]);
                 }
                 result += "], axes=[";
                 for (size_t i = 0; i < self.axes.size(); ++i)
                 {
                     if (i > 0)
                         result += ", ";
                     result += std::to_string(self.axes[i]);
                 }
                 result += "], is_valid=" + std::to_string(self.is_valid) + ")";
                 return result;
             });

    py::class_<GamepadOutputRecordT, std::shared_ptr<GamepadOutputRecordT>>(m, "GamepadOutputRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const GamepadOutputT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<GamepadOutputRecordT>();
                     obj->data = std::make_shared<GamepadOutputT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly(
            "data", [](const GamepadOutputRecordT& self) -> std::shared_ptr<GamepadOutputT> { return self.data; })
        .def_readonly("timestamp", &GamepadOutputRecordT::timestamp)
        .def("__repr__", [](const GamepadOutputRecordT& self)
             { return "GamepadOutputRecord(data=" + std::string(self.data ? "GamepadOutput(...)" : "None") + ")"; });

    py::class_<GamepadOutputTrackedT, std::shared_ptr<GamepadOutputTrackedT>>(m, "GamepadOutputTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const GamepadOutputT& data)
                 {
                     auto obj = std::make_shared<GamepadOutputTrackedT>();
                     obj->data = std::make_shared<GamepadOutputT>(data);
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly(
            "data", [](const GamepadOutputTrackedT& self) -> std::shared_ptr<GamepadOutputT> { return self.data; })
        .def("__repr__", [](const GamepadOutputTrackedT& self)
             { return std::string("GamepadOutputTrackedT(data=") + (self.data ? "GamepadOutput(...)" : "None") + ")"; });
}

} // namespace core
