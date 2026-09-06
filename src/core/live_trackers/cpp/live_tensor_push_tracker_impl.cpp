// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_tensor_push_tracker_impl.hpp"

#include <oxr_utils/os_time.hpp>

#include <utility>

namespace core
{

LiveTensorPushTrackerImpl::LiveTensorPushTrackerImpl(std::unique_ptr<ISchemaPushChannel> channel)
    : pusher_(std::move(channel))
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
