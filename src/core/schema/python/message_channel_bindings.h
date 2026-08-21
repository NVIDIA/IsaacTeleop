// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the message channel FlatBuffer schema.
// Types: MessageChannelMessages (table) and its Tracked / Record wrappers, exposed as
// encoded views. This is the one surviving wrapper: its payload is a list, so a table
// is still needed to hold the vector.

#pragma once

#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/message_channel_generated.h>

#include <memory>
#include <string>
#include <vector>

namespace py = pybind11;

namespace core
{

inline void bind_message_channel(py::module& m)
{
    serialized_class<MessageChannelMessages>(m, "MessageChannelMessages", "Encoded opaque message payload.")
        .def(py::init(
                 [](py::bytes payload)
                 {
                     MessageChannelMessagesT native;
                     const std::string data = payload;
                     native.payload.assign(data.begin(), data.end());
                     return pack<MessageChannelMessages>(native);
                 }),
             py::arg("payload") = py::bytes(), "Encode a message payload.")
        .def_property_readonly("payload",
                               [](const Serialized<MessageChannelMessages>& self)
                               {
                                   const auto* payload = self ? self->payload() : nullptr;
                                   return payload != nullptr ?
                                              py::bytes(reinterpret_cast<const char*>(payload->data()), payload->size()) :
                                              py::bytes();
                               });

    bind_record<MessageChannelMessagesRecord, MessageChannelMessages>(
        m, "MessageChannelMessagesRecord", "MessageChannelMessages");

    // Unlike the single-payload wrappers, `data` here is the batch drained in one frame.
    // It stays a list (empty, never None) so "nothing arrived" and "channel inactive" read
    // the same way they always have.
    serialized_class<MessageChannelMessagesTracked>(
        m, "MessageChannelMessagesTracked", "Encoded batch of messages drained during one update.")
        .def(py::init(
                 [](const std::vector<Serialized<MessageChannelMessages>>& data)
                 {
                     MessageChannelMessagesTrackedT native;
                     native.data = to_native_vector(data, "data");
                     return pack<MessageChannelMessagesTracked>(native);
                 }),
             py::arg("data") = std::vector<Serialized<MessageChannelMessages>>{},
             "Encode a batch of messages. Omit `data` for an empty batch.")
        .def_property_readonly("data", [](const Serialized<MessageChannelMessagesTracked>& self)
                               { return narrow_vector(self, self->data()); })
        .def("__repr__",
             [](const Serialized<MessageChannelMessagesTracked>& self)
             {
                 const auto* encoded = self->data();
                 return "MessageChannelMessagesTracked(data=[" +
                        std::to_string(encoded != nullptr ? encoded->size() : 0) + " messages])";
             });
}

} // namespace core
