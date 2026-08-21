// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/serialized.hpp>

#include <cstdint>
#include <vector>

namespace core
{

struct MessageChannelMessagesTracked;

enum class MessageChannelStatus : int32_t
{
    CONNECTING = 0,
    CONNECTED = 1,
    SHUTTING = 2,
    DISCONNECTED = 3,
    UNKNOWN = -1,
};

class IMessageChannelTrackerImpl : public ITrackerImpl
{
public:
    virtual MessageChannelStatus get_status() const = 0;
    virtual const Serialized<MessageChannelMessagesTracked>& get_messages() const = 0;
    virtual void send_message(const std::vector<uint8_t>& payload) const = 0;
};

} // namespace core
