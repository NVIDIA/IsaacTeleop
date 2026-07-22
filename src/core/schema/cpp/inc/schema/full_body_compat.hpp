// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Deprecated back-compat aliases for the full-body schema types.
//
// The full-body FlatBuffers schema was renamed from the vendor-specific "...Pico"
// names to vendor-neutral names (FullBodyPosePico -> FullBodyPose, BodyJointPico ->
// BodyJoint, ...). Include this header to keep pre-rename identifiers compiling; new
// code should use the generic names in <schema/full_body_generated.h> directly.
//
// The wire format is unchanged: the aliases resolve to the same generated types, and
// the FlatBuffer field IDs / enum values are identical, so recordings round-trip.

#pragma once

#include <schema/full_body_generated.h>

namespace core
{

// ---- Table / struct / record type aliases -------------------------------------
using FullBodyPosePico [[deprecated("renamed to core::FullBodyPose")]] = FullBodyPose;
using FullBodyPosePicoT [[deprecated("renamed to core::FullBodyPoseT")]] = FullBodyPoseT;
using FullBodyPosePicoTracked [[deprecated("renamed to core::FullBodyPoseTracked")]] = FullBodyPoseTracked;
using FullBodyPosePicoTrackedT [[deprecated("renamed to core::FullBodyPoseTrackedT")]] = FullBodyPoseTrackedT;
using FullBodyPosePicoRecord [[deprecated("renamed to core::FullBodyPoseRecord")]] = FullBodyPoseRecord;
using FullBodyPosePicoRecordT [[deprecated("renamed to core::FullBodyPoseRecordT")]] = FullBodyPoseRecordT;
using BodyJointsPico [[deprecated("renamed to core::BodyJoints")]] = BodyJoints;

// ---- Enum type + enumerator aliases -------------------------------------------
// BodyJointPico -> BodyJoint; the BodyJointPico_* enumerators below keep identical
// numeric values. Each is [[deprecated]] in favor of the matching BodyJoint_*.
using BodyJointPico [[deprecated("renamed to core::BodyJoint")]] = BodyJoint;

[[deprecated]] inline constexpr BodyJoint BodyJointPico_PELVIS = BodyJoint_PELVIS;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_LEFT_HIP = BodyJoint_LEFT_HIP;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_RIGHT_HIP = BodyJoint_RIGHT_HIP;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_SPINE1 = BodyJoint_SPINE1;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_LEFT_KNEE = BodyJoint_LEFT_KNEE;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_RIGHT_KNEE = BodyJoint_RIGHT_KNEE;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_SPINE2 = BodyJoint_SPINE2;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_LEFT_ANKLE = BodyJoint_LEFT_ANKLE;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_RIGHT_ANKLE = BodyJoint_RIGHT_ANKLE;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_SPINE3 = BodyJoint_SPINE3;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_LEFT_FOOT = BodyJoint_LEFT_FOOT;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_RIGHT_FOOT = BodyJoint_RIGHT_FOOT;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_NECK = BodyJoint_NECK;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_LEFT_COLLAR = BodyJoint_LEFT_COLLAR;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_RIGHT_COLLAR = BodyJoint_RIGHT_COLLAR;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_HEAD = BodyJoint_HEAD;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_LEFT_SHOULDER = BodyJoint_LEFT_SHOULDER;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_RIGHT_SHOULDER = BodyJoint_RIGHT_SHOULDER;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_LEFT_ELBOW = BodyJoint_LEFT_ELBOW;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_RIGHT_ELBOW = BodyJoint_RIGHT_ELBOW;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_LEFT_WRIST = BodyJoint_LEFT_WRIST;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_RIGHT_WRIST = BodyJoint_RIGHT_WRIST;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_LEFT_HAND = BodyJoint_LEFT_HAND;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_RIGHT_HAND = BodyJoint_RIGHT_HAND;
[[deprecated]] inline constexpr BodyJoint BodyJointPico_NUM_JOINTS = BodyJoint_NUM_JOINTS;

} // namespace core
