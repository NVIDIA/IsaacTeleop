// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/message_channel_tracker_base.hpp>
#include <schema/message_channel_generated.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace core
{

class MessageChannelTracker : public ITracker
{
public:
    static constexpr size_t DEFAULT_MAX_MESSAGE_SIZE = 64 * 1024;
    static constexpr size_t CHANNEL_UUID_SIZE = 16;

    explicit MessageChannelTracker(const std::array<uint8_t, CHANNEL_UUID_SIZE>& channel_uuid,
                                   const std::string& channel_name = "",
                                   size_t max_message_size = DEFAULT_MAX_MESSAGE_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    MessageChannelStatus get_status(const ITrackerSession& session) const;
    const MessageChannelMessagesTrackedT& get_messages(const ITrackerSession& session) const;
    void send_message(const ITrackerSession& session, const std::vector<uint8_t>& payload) const;

    const std::array<uint8_t, CHANNEL_UUID_SIZE>& channel_uuid() const
    {
        return channel_uuid_;
    }

    const std::string& channel_name() const
    {
        return channel_name_;
    }

    size_t max_message_size() const
    {
        return max_message_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "MessageChannelTracker";

    std::array<uint8_t, CHANNEL_UUID_SIZE> channel_uuid_{};
    std::string channel_name_;
    size_t max_message_size_{ DEFAULT_MAX_MESSAGE_SIZE };
};

} // namespace core
