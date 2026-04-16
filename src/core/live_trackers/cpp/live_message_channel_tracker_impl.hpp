// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_trackers/message_channel_tracker.hpp>
#include <mcap/tracker_channels.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/message_channel_generated.h>

#include <XR_NV_opaque_data_channel.h>
#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using MessageChannelMcapChannels = McapTrackerChannels<MessageChannelMessagesRecord, MessageChannelMessages>;

class LiveMessageChannelTrackerImpl : public IMessageChannelTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return { XR_NV_OPAQUE_DATA_CHANNEL_EXTENSION_NAME };
    }
    static std::unique_ptr<MessageChannelMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                            std::string_view base_name);

    LiveMessageChannelTrackerImpl(const OpenXRSessionHandles& handles,
                                  const MessageChannelTracker* tracker,
                                  std::unique_ptr<MessageChannelMcapChannels> mcap_channels = nullptr);
    ~LiveMessageChannelTrackerImpl() override;

    LiveMessageChannelTrackerImpl(const LiveMessageChannelTrackerImpl&) = delete;
    LiveMessageChannelTrackerImpl& operator=(const LiveMessageChannelTrackerImpl&) = delete;
    LiveMessageChannelTrackerImpl(LiveMessageChannelTrackerImpl&&) = delete;
    LiveMessageChannelTrackerImpl& operator=(LiveMessageChannelTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    MessageChannelStatus get_status() const override;
    const MessageChannelMessagesTrackedT& get_messages() const override;
    void send_message(const std::vector<uint8_t>& payload) const override;

private:
    void initialize_functions();
    XrSystemId resolve_system_id() const;
    MessageChannelStatus query_status() const;
    void create_channel();
    void destroy_channel() noexcept;
    bool try_reopen_channel();
    XrUuidEXT make_uuid(const std::array<uint8_t, MessageChannelTracker::CHANNEL_UUID_SIZE>& channel_uuid) const;

    OpenXRSessionHandles handles_;
    const MessageChannelTracker* tracker_{ nullptr };
    XrSystemId system_id_{ XR_NULL_SYSTEM_ID };
    XrUuidEXT channel_uuid_{};
    XrOpaqueDataChannelNV channel_{ XR_NULL_HANDLE };

    PFN_xrCreateOpaqueDataChannelNV create_channel_fn_{ nullptr };
    PFN_xrDestroyOpaqueDataChannelNV destroy_channel_fn_{ nullptr };
    PFN_xrGetOpaqueDataChannelStateNV get_state_fn_{ nullptr };
    PFN_xrSendOpaqueDataChannelNV send_fn_{ nullptr };
    PFN_xrReceiveOpaqueDataChannelNV receive_fn_{ nullptr };
    PFN_xrShutdownOpaqueDataChannelNV shutdown_fn_{ nullptr };
    PFN_xrGetSystem get_system_fn_{ nullptr };

    XrTimeConverter time_converter_;
    int64_t last_update_time_ = 0;
    MessageChannelMessagesTrackedT messages_;
    std::vector<uint8_t> receive_buffer_;
    std::unique_ptr<MessageChannelMcapChannels> mcap_channels_;
};

} // namespace core
