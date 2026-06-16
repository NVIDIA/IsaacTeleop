// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_haptic_command_reader_tracker_impl.hpp"

namespace core
{

namespace
{

// Canonical identifiers for the vendor-neutral HapticCommand payload. The
// producer (TensorPushTracker created by PushTensorHapticDevice) pushes under
// the same "haptic_command" tensor identifier; SchemaTrackerBase filters by
// collection_id, these strings just keep the runtime's per-tensor diagnostics
// aligned.
constexpr const char* kHapticCommandTensorIdentifier = "haptic_command";
constexpr const char* kHapticCommandLocalizedName = "HapticCommand";

SchemaTrackerConfig make_haptic_command_reader_config(const HapticCommandReaderTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_payload_size();
    cfg.tensor_identifier = kHapticCommandTensorIdentifier;
    cfg.localized_name = kHapticCommandLocalizedName;
    return cfg;
}

} // namespace

LiveHapticCommandReaderTrackerImpl::LiveHapticCommandReaderTrackerImpl(const OpenXRSessionHandles& handles,
                                                                       const HapticCommandReaderTracker* tracker)
    : schema_reader_(handles, make_haptic_command_reader_config(tracker), /*mcap_channels=*/nullptr)
{
}

void LiveHapticCommandReaderTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    schema_reader_.update(tracked_.data);
}

const HapticCommandTrackedT& LiveHapticCommandReaderTrackerImpl::get_data() const
{
    return tracked_;
}

} // namespace core
