// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python module entry point for TeleopCore schema bindings.

#include <pybind11/pybind11.h>

// Include binding definitions.
#include "tensor_bindings.h"
#include "pose_bindings.h"

namespace py = pybind11;

PYBIND11_MODULE(_schema, m) {
    m.doc() = "TeleopCore Schema - FlatBuffer message types for teleoperation";

    // Bind tensor types (enums, structs, TensorT).
    core::bind_tensor(m);

    // Bind pose types (Point, Quaternion, Pose structs).
    core::bind_pose(m);
}

