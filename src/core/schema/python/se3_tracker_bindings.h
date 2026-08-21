// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Se3TrackerPose FlatBuffer schema.
// Se3TrackerPose is a table (pose + is_valid), exposed as an encoded view.

#pragma once

#include "pose_bindings.h"
#include "schema_serialized.h"

#include <pybind11/pybind11.h>
#include <schema/se3_tracker_generated.h>

#include <memory>
#include <string>

namespace py = pybind11;

namespace core
{

inline void bind_se3_tracker(py::module& m)
{
    serialized_class<Se3TrackerPose>(m, "Se3TrackerPose",
                                     "Encoded SE3 tracker pose. Gate on is_valid before consuming pose -- the pose "
                                     "contents are unspecified while tracking is lost.")
        .def(py::init(
                 [](const Pose& pose, bool is_valid)
                 {
                     Se3TrackerPoseT native;
                     native.pose = std::make_shared<Pose>(pose);
                     native.is_valid = is_valid;
                     return pack<Se3TrackerPose>(native);
                 }),
             py::arg("pose") = Pose(), py::arg("is_valid") = false,
             "Encode an SE3 pose. Defaults to an all-zero pose that is not valid.")
        .def_property_readonly("pose", field(&Se3TrackerPose::pose), py::return_value_policy::reference_internal)
        .def_property_readonly("is_valid", field(&Se3TrackerPose::is_valid))
        .def("__repr__",
             [](const Serialized<Se3TrackerPose>& self)
             {
                 const Pose* pose = self->pose();
                 const std::string pose_str = pose != nullptr ? pose_repr(*pose) : "None";
                 return "Se3TrackerPose(pose=" + pose_str + ", is_valid=" + (self->is_valid() ? "True" : "False") + ")";
             });

    bind_record<Se3TrackerPoseRecord, Se3TrackerPose>(m, "Se3TrackerPoseRecord", "Se3TrackerPose");
}

} // namespace core
