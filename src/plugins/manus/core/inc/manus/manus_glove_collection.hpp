// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

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

// Outbound flex-sensor (Manus RawDeviceData) collections pushed as JointStateOutput
// with tensor identifier "joint_state". Hosts discover them via JointStateSource.
//
// Packing (35 positional joints j0..j34): for sensor i in thumb→pinky order
// (i = 0..4), joints j[7*i .. 7*i+6] hold one SE(3) tip as
//   [x, y, z, qx, qy, qz, qw]
// in meters / xyzw, in the Manus SDK frame after the plugin's VUH coordinate
// setup. All 35 joints are valid=true only when sensorCount >= 5; otherwise the
// plugin skips the push so the host sees "no sensors".
//
// These are raw Manus flex transforms (same source as SharpaManusClient's
// RawDeviceData callback).
inline constexpr const char* MANUS_SENSORS_COLLECTION_PREFIX = "manus_sensors";
inline constexpr const char* MANUS_SENSORS_LEFT_COLLECTION_ID = "manus_sensors_left";
inline constexpr const char* MANUS_SENSORS_RIGHT_COLLECTION_ID = "manus_sensors_right";

inline constexpr int kManusSensorCount = 5;
inline constexpr int kManusSensorPoseFloats = 7; // xyz + quat xyzw
inline constexpr int kManusSensorJointCount = kManusSensorCount * kManusSensorPoseFloats; // 35

} // namespace manus
} // namespace plugins
