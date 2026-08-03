// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Shared scaffolding for binding FlatBuffer tables to Python as encoded views.
//
// Python sees one class per table, backed by core::Serialized<Table>: reads go through
// the generated accessors straight into the buffer, and no object-API (`-T`) type is
// ever exposed. Structs (Pose, HandJoints, ...) are unaffected -- flatc emits one
// struct type for both APIs, so their existing bindings and the zero-copy NumPy views
// in schema_array_views.h keep working, reached through a table view that owns the
// buffer they alias.
//
// Construction from Python goes the other way: a constructor builds a `-T` as a local,
// encodes it, and returns the view. That keeps the encoder honest (it is the generated
// Pack, so the layout always matches the C++ readers) while the `-T` stays invisible.
//
// Every Record wrapper has the same shape, so bind_record() below covers them; each
// schema's binding header only has to describe its own payload table. Trackers publish
// their payload table directly -- an empty view is how absence is expressed -- so there
// is no wrapper binding here.

#pragma once

#include <pybind11/pybind11.h>
#include <schema/serialized.hpp>
#include <schema/timestamp_generated.h>
#include <schema/tracked.hpp>

#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace py = pybind11;

namespace core
{

//! Python class for a table view. Chain the table's own fields onto the result.
template <typename T>
py::class_<Serialized<T>> serialized_class(py::module& m, const char* name, const char* doc)
{
    return py::class_<Serialized<T>>(m, name, doc)
        // Always true in practice: an absent payload reaches Python as None, never as an
        // empty view. Kept so that a view which somehow arrived empty still reports it
        // rather than silently answering field reads with defaults.
        .def(
            "__bool__", [](const Serialized<T>& self) { return static_cast<bool>(self); },
            "False when the payload is absent.");
}

/*!
 * @brief Converts handles into the native element vector a table's vector field takes.
 *
 * FlatBuffers cannot splice a finished buffer into another one, so a constructor composing
 * a table around payloads the caller already built has to go back through the object API.
 * A construction-time cost only -- the read path never unpacks.
 *
 * A vector field is the one place a null element is fatal: the generated `Pack` null-checks
 * an optional table field but dereferences every vector element unconditionally. `field`
 * names the vector in the message.
 */
template <typename DataT>
std::vector<std::shared_ptr<typename DataT::NativeTableType>> to_native_vector(const std::vector<Serialized<DataT>>& handles,
                                                                               const char* field)
{
    std::vector<std::shared_ptr<typename DataT::NativeTableType>> natives;
    natives.reserve(handles.size());
    for (const auto& handle : handles)
    {
        if (!handle)
        {
            throw py::value_error(std::string(field) + ": entries must be non-empty");
        }
        auto native = std::make_shared<typename DataT::NativeTableType>();
        handle->UnPackTo(native.get());
        natives.push_back(std::move(native));
    }
    return natives;
}

//! Binds a `Record` wrapper (an MCAP payload: data plus its capture timestamp).
template <typename RecordT, typename DataT>
void bind_record(py::module& m, const char* name, const char* data_name)
{
    serialized_class<RecordT>(m, name, "Encoded MCAP record: a payload plus the timestamp it was captured at.")
        .def(py::init<>(), "Construct an empty record (.data and .timestamp are None).")
        .def(py::init(
                 [](const Serialized<DataT>* data, const DeviceDataTimestamp& timestamp)
                 {
                     typename RecordT::NativeTableType native;
                     if (data != nullptr && *data)
                     {
                         native.data = std::make_shared<typename DataT::NativeTableType>();
                         (*data)->UnPackTo(native.data.get());
                     }
                     native.timestamp = std::make_shared<DeviceDataTimestamp>(timestamp);
                     return pack<RecordT>(native);
                 }),
             py::arg("data").none(true), py::arg("timestamp"),
             "Encode a record from a payload and its timestamp. `data` may be None: MCAP "
             "carries payload-less records, such as the message channel's frame sentinel.")

        // Unlike Tracked, a Record cannot fold its no-arg form into defaults: `timestamp` is a
        // struct with no meaningful default, and an empty record is a distinct thing from one
        // stamped at time zero.
        .def_property_readonly(
            "data",
            [](const Serialized<RecordT>& self) -> py::object
            {
                const DataT* data = payload(self);
                return data != nullptr ? py::cast(self.narrow(data)) : py::none();
            },
            "The recorded payload, or None when absent.")
        .def_property_readonly(
            "timestamp", [](const Serialized<RecordT>& self) { return self ? self->timestamp() : nullptr; },
            py::return_value_policy::reference_internal, "Capture timestamp, or None when absent.")
        .def("__repr__",
             [name, data_name](const Serialized<RecordT>& self)
             {
                 return std::string(name) +
                        "(data=" + (payload(self) != nullptr ? std::string(data_name) + "(...)" : "None") + ")";
             });
}

} // namespace core
