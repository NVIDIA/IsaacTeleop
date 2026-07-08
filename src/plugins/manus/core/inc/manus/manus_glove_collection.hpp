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

} // namespace manus
} // namespace plugins
