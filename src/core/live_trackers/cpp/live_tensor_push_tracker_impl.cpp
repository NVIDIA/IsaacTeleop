// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_tensor_push_tracker_impl.hpp"

#include <oxr_utils/os_time.hpp>

namespace core
{

namespace
{

SchemaPusherConfig make_tensor_push_config(const TensorPushTracker* tracker)
{
    SchemaPusherConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_payload_size();
    cfg.tensor_identifier = tracker->tensor_identifier();
    cfg.localized_name = tracker->tensor_identifier();
    return cfg;
}

} // namespace

LiveTensorPushTrackerImpl::LiveTensorPushTrackerImpl(const OpenXRSessionHandles& handles, const TensorPushTracker* tracker)
    : pusher_(handles, make_tensor_push_config(tracker))
{
}

void LiveTensorPushTrackerImpl::update(int64_t monotonic_time_ns)
{
    last_update_time_ns_ = monotonic_time_ns;
}

void LiveTensorPushTrackerImpl::push(const std::vector<uint8_t>& payload) const
{
    // Prefer the most-recent session tick so pushes share the session's
    // monotonic-clock domain; fall back to "now" for pushes that beat the
    // first update(). Synthesised commands have no raw-device clock, so both
    // timestamps get the same value.
    const int64_t now_ns = last_update_time_ns_ > 0 ? last_update_time_ns_ : core::os_monotonic_now_ns();
    pusher_.push_buffer(payload.data(), payload.size(), now_ns, now_ns);
}

} // namespace core
