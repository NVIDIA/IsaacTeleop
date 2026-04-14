// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/opaque_data_channel_tracker.hpp"

namespace core
{

OpaqueDataChannelTracker::OpaqueDataChannelTracker(std::array<uint8_t, 16> uuid)
    : uuid_(uuid)
{
}

std::string_view OpaqueDataChannelTracker::get_name() const
{
    return TRACKER_NAME;
}

std::optional<std::vector<uint8_t>> OpaqueDataChannelTracker::get_latest_message(const ITrackerSession& session) const
{
    return static_cast<const IOpaqueDataChannelTrackerImpl&>(session.get_tracker_impl(*this)).get_latest_message();
}

const std::array<uint8_t, 16>& OpaqueDataChannelTracker::get_uuid() const
{
    return uuid_;
}

} // namespace core
