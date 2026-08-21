// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Keyboard FlatBuffer schema.
// Types: KeyboardOutput (table).

#pragma once

#include <pybind11/pybind11.h>
#include <schema/keyboard_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_keyboard(py::module& m)
{
    py::class_<KeyboardOutputT, std::shared_ptr<KeyboardOutputT>>(m, "KeyboardOutput")
        .def(py::init([]() { return std::make_shared<KeyboardOutputT>(); }))
        .def(py::init(
                 [](bool key_w, bool key_a, bool key_s, bool key_d, bool key_q, bool key_e, bool key_z, bool key_x,
                    bool key_t, bool key_g, bool key_c, bool key_v, bool key_k, bool is_valid)
                 {
                     auto obj = std::make_shared<KeyboardOutputT>();
                     obj->key_w = key_w;
                     obj->key_a = key_a;
                     obj->key_s = key_s;
                     obj->key_d = key_d;
                     obj->key_q = key_q;
                     obj->key_e = key_e;
                     obj->key_z = key_z;
                     obj->key_x = key_x;
                     obj->key_t = key_t;
                     obj->key_g = key_g;
                     obj->key_c = key_c;
                     obj->key_v = key_v;
                     obj->key_k = key_k;
                     obj->is_valid = is_valid;
                     return obj;
                 }),
             py::arg("key_w"), py::arg("key_a"), py::arg("key_s"), py::arg("key_d"), py::arg("key_q"), py::arg("key_e"),
             py::arg("key_z"), py::arg("key_x"), py::arg("key_t"), py::arg("key_g"), py::arg("key_c"), py::arg("key_v"),
             py::arg("key_k"), py::arg("is_valid"))
        .def_property(
            "key_w", [](const KeyboardOutputT& self) { return self.key_w; },
            [](KeyboardOutputT& self, bool val) { self.key_w = val; })
        .def_property(
            "key_a", [](const KeyboardOutputT& self) { return self.key_a; },
            [](KeyboardOutputT& self, bool val) { self.key_a = val; })
        .def_property(
            "key_s", [](const KeyboardOutputT& self) { return self.key_s; },
            [](KeyboardOutputT& self, bool val) { self.key_s = val; })
        .def_property(
            "key_d", [](const KeyboardOutputT& self) { return self.key_d; },
            [](KeyboardOutputT& self, bool val) { self.key_d = val; })
        .def_property(
            "key_q", [](const KeyboardOutputT& self) { return self.key_q; },
            [](KeyboardOutputT& self, bool val) { self.key_q = val; })
        .def_property(
            "key_e", [](const KeyboardOutputT& self) { return self.key_e; },
            [](KeyboardOutputT& self, bool val) { self.key_e = val; })
        .def_property(
            "key_z", [](const KeyboardOutputT& self) { return self.key_z; },
            [](KeyboardOutputT& self, bool val) { self.key_z = val; })
        .def_property(
            "key_x", [](const KeyboardOutputT& self) { return self.key_x; },
            [](KeyboardOutputT& self, bool val) { self.key_x = val; })
        .def_property(
            "key_t", [](const KeyboardOutputT& self) { return self.key_t; },
            [](KeyboardOutputT& self, bool val) { self.key_t = val; })
        .def_property(
            "key_g", [](const KeyboardOutputT& self) { return self.key_g; },
            [](KeyboardOutputT& self, bool val) { self.key_g = val; })
        .def_property(
            "key_c", [](const KeyboardOutputT& self) { return self.key_c; },
            [](KeyboardOutputT& self, bool val) { self.key_c = val; })
        .def_property(
            "key_v", [](const KeyboardOutputT& self) { return self.key_v; },
            [](KeyboardOutputT& self, bool val) { self.key_v = val; })
        .def_property(
            "key_k", [](const KeyboardOutputT& self) { return self.key_k; },
            [](KeyboardOutputT& self, bool val) { self.key_k = val; })
        .def_property(
            "is_valid", [](const KeyboardOutputT& self) { return self.is_valid; },
            [](KeyboardOutputT& self, bool val) { self.is_valid = val; })
        .def("__repr__",
             [](const KeyboardOutputT& self)
             {
                 std::string result = "KeyboardOutput(";
                 result += "key_w=" + std::to_string(self.key_w);
                 result += ", key_a=" + std::to_string(self.key_a);
                 result += ", key_s=" + std::to_string(self.key_s);
                 result += ", key_d=" + std::to_string(self.key_d);
                 result += ", key_q=" + std::to_string(self.key_q);
                 result += ", key_e=" + std::to_string(self.key_e);
                 result += ", key_z=" + std::to_string(self.key_z);
                 result += ", key_x=" + std::to_string(self.key_x);
                 result += ", key_t=" + std::to_string(self.key_t);
                 result += ", key_g=" + std::to_string(self.key_g);
                 result += ", key_c=" + std::to_string(self.key_c);
                 result += ", key_v=" + std::to_string(self.key_v);
                 result += ", key_k=" + std::to_string(self.key_k);
                 result += ", is_valid=" + std::to_string(self.is_valid);
                 result += ")";
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
