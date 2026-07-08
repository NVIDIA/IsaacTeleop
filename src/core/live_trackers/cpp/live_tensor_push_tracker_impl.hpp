// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/tensor_push_tracker_base.hpp>
#include <deviceio_trackers/tensor_push_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <pusherio/schema_pusher.hpp>

#include <cstdint>
#include <vector>

namespace core
{

// Wraps core::SchemaPusher; owns the XR_NVX1_push_tensor handle.
class LiveTensorPushTrackerImpl : public ITensorPushTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaPusher::get_required_extensions();
    }

    LiveTensorPushTrackerImpl(const OpenXRSessionHandles& handles, const TensorPushTracker* tracker);

    LiveTensorPushTrackerImpl(const LiveTensorPushTrackerImpl&) = delete;
    LiveTensorPushTrackerImpl& operator=(const LiveTensorPushTrackerImpl&) = delete;
    LiveTensorPushTrackerImpl(LiveTensorPushTrackerImpl&&) = delete;
    LiveTensorPushTrackerImpl& operator=(LiveTensorPushTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    void push(const std::vector<uint8_t>& payload) const override;

private:
    // `mutable` keeps push() `const` (mirrors MessageChannelTracker::send_message);
    // SchemaPusher::push_buffer is non-const but each call is just a runtime side effect.
    mutable SchemaPusher pusher_;
    int64_t last_update_time_ns_{ 0 };
};

} // namespace core
