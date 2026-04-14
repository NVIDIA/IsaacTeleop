// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/opaque_data_channel_tracker_base.hpp>

#include <array>
#include <cstdint>
#include <optional>
#include <string_view>
#include <vector>

namespace core
{

// Receives arbitrary bytes from a CloudXR opaque data channel identified by UUID.
// The channel is created and polled by the live implementation; this public
// tracker exposes the latest received message to Python DeviceIO source nodes.
class OpaqueDataChannelTracker : public ITracker
{
public:
    explicit OpaqueDataChannelTracker(std::array<uint8_t, 16> uuid);

    std::string_view get_name() const override;

    std::optional<std::vector<uint8_t>> get_latest_message(const ITrackerSession& session) const;

    const std::array<uint8_t, 16>& get_uuid() const;

private:
    static constexpr const char* TRACKER_NAME = "OpaqueDataChannelTracker";
    std::array<uint8_t, 16> uuid_;
};

} // namespace core
