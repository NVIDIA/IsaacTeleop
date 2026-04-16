// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/message_channel_tracker.hpp"

#include <stdexcept>

namespace core
{

MessageChannelTracker::MessageChannelTracker(const std::array<uint8_t, CHANNEL_UUID_SIZE>& channel_uuid,
                                             const std::string& channel_name,
                                             size_t max_message_size)
    : channel_uuid_(channel_uuid), channel_name_(channel_name), max_message_size_(max_message_size)
{
    if (max_message_size_ == 0)
    {
        throw std::invalid_argument("MessageChannelTracker: max_message_size must be > 0");
    }
}

MessageChannelStatus MessageChannelTracker::get_status(const ITrackerSession& session) const
{
    return static_cast<const IMessageChannelTrackerImpl&>(session.get_tracker_impl(*this)).get_status();
}

const MessageChannelMessagesTrackedT& MessageChannelTracker::get_messages(const ITrackerSession& session) const
{
    return static_cast<const IMessageChannelTrackerImpl&>(session.get_tracker_impl(*this)).get_messages();
}

void MessageChannelTracker::send_message(const ITrackerSession& session, const std::vector<uint8_t>& payload) const
{
    static_cast<const IMessageChannelTrackerImpl&>(session.get_tracker_impl(*this)).send_message(payload);
}

} // namespace core
