// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Pose FlatBuffer schema.

#pragma once

#include <memory>

#include "pybind11/pybind11.h"
#include "pybind11/numpy.h"
#include "pybind11/stl.h"

#include <schema/pose_generated.h>
#include <schema/tensor_generated.h>

// Include tensor bindings for numpy conversion helpers.
#include "tensor_bindings.h"

namespace py = pybind11;

namespace core {

inline void bind_pose(py::module& m) {
    py::class_<PoseT, std::unique_ptr<PoseT>>(m, "PoseT")
        .def(py::init<>())
        .def_property(
            "position",
            [](const PoseT& self) -> py::object {
                if (self.position) {
                    return py::cast(self.position.get(), py::return_value_policy::reference);
                }
                return py::none();
            },
            [](PoseT& self, py::object value) {
                if (py::isinstance<py::array>(value)) {
                    self.position = numpy_to_tensor(value.cast<py::array>());
                } else if (py::isinstance<TensorT>(value)) {
                    // Copy the tensor.
                    auto* src = value.cast<TensorT*>();
                    self.position = std::make_unique<TensorT>(*src);
                } else if (value.is_none()) {
                    self.position.reset();
                } else {
                    throw std::runtime_error(
                        "position must be a numpy array, TensorT, or None");
                }
            })
        .def_property(
            "orientation",
            [](const PoseT& self) -> py::object {
                if (self.orientation) {
                    return py::cast(self.orientation.get(), py::return_value_policy::reference);
                }
                return py::none();
            },
            [](PoseT& self, py::object value) {
                if (py::isinstance<py::array>(value)) {
                    self.orientation = numpy_to_tensor(value.cast<py::array>());
                } else if (py::isinstance<TensorT>(value)) {
                    // Copy the tensor.
                    auto* src = value.cast<TensorT*>();
                    self.orientation = std::make_unique<TensorT>(*src);
                } else if (value.is_none()) {
                    self.orientation.reset();
                } else {
                    throw std::runtime_error(
                        "orientation must be a numpy array, TensorT, or None");
                }
            });
}

}  // namespace core


