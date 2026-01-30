// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python module entry point for TeleopCore schema bindings.

#include <pybind11/pybind11.h>

// Include binding definitions.
#include "controller_bindings.h"
#include "hand_bindings.h"
#include "head_bindings.h"
#include "locomotion_bindings.h"
#include "pose_bindings.h"
#include "tensor_bindings.h"

namespace py = pybind11;

PYBIND11_MODULE(_schema, m)
{
    m.doc() = "TeleopCore Schema - FlatBuffer message types for teleoperation";

    // Bind tensor types (enums, structs, TensorT).
    core::bind_tensor(m);

    // Bind pose types (Point, Quaternion, Pose structs).
    core::bind_pose(m);

    // Bind head types (HeadPoseT table).
    core::bind_head(m);

    // Bind hand types (HandJointPose, HandJoints structs, HandPoseT table).
    core::bind_hand(m);

    // Bind controller types (ControllerInputState, ControllerPose structs, ControllerSnapshotT table, Hand enum).
    core::bind_controller(m);

    // Bind locomotion types (Twist struct, LocomotionCommand table).
    core::bind_locomotion(m);
}
