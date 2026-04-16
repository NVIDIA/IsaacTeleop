// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/message_channel_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>

namespace py = pybind11;

namespace core
{

inline void bind_message_channel(py::module& m)
{
    py::class_<MessageChannelMessagesT, std::shared_ptr<MessageChannelMessagesT>>(m, "MessageChannelMessages")
        .def(py::init([]() { return std::make_shared<MessageChannelMessagesT>(); }))
        .def(py::init(
                 [](py::bytes payload)
                 {
                     auto obj = std::make_shared<MessageChannelMessagesT>();
                     std::string data = payload;
                     obj->payload.assign(data.begin(), data.end());
                     return obj;
                 }),
             py::arg("payload"))
        .def_property(
            "payload",
            [](const MessageChannelMessagesT& self)
            { return py::bytes(reinterpret_cast<const char*>(self.payload.data()), self.payload.size()); },
            [](MessageChannelMessagesT& self, py::bytes payload)
            {
                std::string data = payload;
                self.payload.assign(data.begin(), data.end());
            });

    py::class_<MessageChannelMessagesRecordT, std::shared_ptr<MessageChannelMessagesRecordT>>(
        m, "MessageChannelMessagesRecord")
        .def(py::init<>())
        .def(py::init(
                 [](const MessageChannelMessagesT& data, const DeviceDataTimestamp& timestamp)
                 {
                     auto obj = std::make_shared<MessageChannelMessagesRecordT>();
                     obj->data = std::make_shared<MessageChannelMessagesT>(data);
                     obj->timestamp = std::make_shared<core::DeviceDataTimestamp>(timestamp);
                     return obj;
                 }),
             py::arg("data"), py::arg("timestamp"))
        .def_property_readonly("data",
                               [](const MessageChannelMessagesRecordT& self) -> std::shared_ptr<MessageChannelMessagesT>
                               { return self.data; })
        .def_readonly("timestamp", &MessageChannelMessagesRecordT::timestamp);

    py::class_<MessageChannelMessagesTrackedT, std::shared_ptr<MessageChannelMessagesTrackedT>>(
        m, "MessageChannelMessagesTrackedT")
        .def(py::init<>())
        .def(py::init(
                 [](const std::vector<std::shared_ptr<MessageChannelMessagesT>>& data)
                 {
                     auto obj = std::make_shared<MessageChannelMessagesTrackedT>();
                     obj->data = data;
                     return obj;
                 }),
             py::arg("data"))
        .def_property_readonly(
            "data",
            [](const MessageChannelMessagesTrackedT& self) -> std::vector<std::shared_ptr<MessageChannelMessagesT>>
            { return self.data; });
}

} // namespace core
