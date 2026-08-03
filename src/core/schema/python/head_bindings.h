// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the HeadPose FlatBuffer schema.
// HeadPose is a table (pose + is_valid), exposed as an encoded view.

#pragma once

#include "pose_bindings.h"
#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <schema/head_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>
#include <string>

namespace py = pybind11;

namespace core
{

inline void bind_head(py::module& m)
{
    serialized_class<HeadPose>(m, "HeadPose", "Encoded head pose: a pose plus its validity flag.")
        .def(py::init(
                 [](const Pose& pose, bool is_valid)
                 {
                     HeadPoseT native;
                     native.pose = std::make_shared<Pose>(pose);
                     native.is_valid = is_valid;
                     return pack<HeadPose>(native);
                 }),
             py::arg("pose") = Pose(), py::arg("is_valid") = false,
             "Encode a head pose. Defaults to an all-zero pose that is not valid.")
        .def_property_readonly(
            "pose", [](const Serialized<HeadPose>& self) { return self ? self->pose() : nullptr; },
            py::return_value_policy::reference_internal)
        .def_property_readonly("is_valid", [](const Serialized<HeadPose>& self) { return self && self->is_valid(); })
        .def("__repr__",
             [](const Serialized<HeadPose>& self)
             {
                 if (!self)
                 {
                     return std::string("HeadPose(<empty>)");
                 }
                 const Pose* pose = self->pose();
                 const std::string pose_str = pose != nullptr ? pose_repr(*pose) : "None";
                 return "HeadPose(pose=" + pose_str + ", is_valid=" + (self->is_valid() ? "True" : "False") + ")";
             });

    bind_record<HeadPoseRecord, HeadPose>(m, "HeadPoseRecord", "HeadPose");
}

} // namespace core
