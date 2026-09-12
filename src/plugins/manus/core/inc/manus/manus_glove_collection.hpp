// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <schema/joint_se3_pose_generated.h>

#include <array>

namespace plugins
{
namespace manus
{

// Vendor binding for the Teleop -> Manus haptic-glove tensor collection.
// The Teleop-side producer is a generic
// isaacteleop.haptic_devices.push_tensor.PushTensorHapticDevice (see the
// isaacteleop.haptic_devices.glove.haptic_glove_device factory and the
// haptic_feedback example). Whatever consumer the app wires must pass this
// same collection_id string so the runtime pairs them by name.
//
// The per-sample buffer size is deliberately NOT configured here: the reader
// (HapticCommandReaderTracker) and the producer (TensorPushTracker) share the
// same DEFAULT_MAX_PAYLOAD_SIZE, so both sides agree without a Manus-specific
// constant that could drift below the producer's collection size (the reader
// rejects a collection whose sample size exceeds its buffer).
inline constexpr const char* MANUS_GLOVE_COLLECTION_ID = "manus_glove_haptic";

// Outbound flex-sensor (Manus RawDeviceData) collections pushed as JointSe3PoseOutput
// with tensor identifier "joint_se3_pose". Hosts read them with a JointSe3PoseTracker and
// look tips up by JointName.
//
// Poses are in meters / xyzw quaternion, in the Manus SDK frame after the plugin's VUH
// coordinate setup. The plugin pushes only a complete five-tip set (sensorCount >= 5);
// otherwise it skips the push so the host sees "no sensors".
//
// These are raw Manus flex transforms (same source as SharpaManusClient's
// RawDeviceData callback).
inline constexpr const char* MANUS_SENSORS_COLLECTION_PREFIX = "manus_sensors";
inline constexpr const char* MANUS_SENSORS_LEFT_COLLECTION_ID = "manus_sensors_left";
inline constexpr const char* MANUS_SENSORS_RIGHT_COLLECTION_ID = "manus_sensors_right";

inline constexpr int kManusSensorCount = 5;

// Manus reports its flex sensors thumb→pinky; this is that order as JointNames.
inline constexpr std::array<core::JointName, kManusSensorCount> kManusSensorJoints = {
    core::JointName_HAND_RAW_THUMB_TIP, core::JointName_HAND_RAW_INDEX_TIP,  core::JointName_HAND_RAW_MIDDLE_TIP,
    core::JointName_HAND_RAW_RING_TIP,  core::JointName_HAND_RAW_LITTLE_TIP,
};

} // namespace manus
} // namespace plugins
