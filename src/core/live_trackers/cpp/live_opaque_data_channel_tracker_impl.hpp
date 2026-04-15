// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/opaque_data_channel_tracker_base.hpp>
#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_session_handles.hpp>

#include <XR_NV_opaque_data_channel.h>

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace core
{

class OpaqueDataChannelTracker;

class LiveOpaqueDataChannelTrackerImpl : public IOpaqueDataChannelTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return { XR_NV_OPAQUE_DATA_CHANNEL_EXTENSION_NAME };
    }

    LiveOpaqueDataChannelTrackerImpl(const OpenXRSessionHandles& handles,
                                     const OpaqueDataChannelTracker* tracker);
    ~LiveOpaqueDataChannelTrackerImpl();

    LiveOpaqueDataChannelTrackerImpl(const LiveOpaqueDataChannelTrackerImpl&) = delete;
    LiveOpaqueDataChannelTrackerImpl& operator=(const LiveOpaqueDataChannelTrackerImpl&) = delete;
    LiveOpaqueDataChannelTrackerImpl(LiveOpaqueDataChannelTrackerImpl&&) = delete;
    LiveOpaqueDataChannelTrackerImpl& operator=(LiveOpaqueDataChannelTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    std::optional<std::vector<uint8_t>> get_latest_message() const override;

private:
    XrInstance instance_;
    XrOpaqueDataChannelNV channel_{ XR_NULL_HANDLE };
    XrOpaqueDataChannelStatusNV status_{ XR_OPAQUE_DATA_CHANNEL_STATUS_CONNECTING_NV };

    PFN_xrCreateOpaqueDataChannelNV pfn_create_{ nullptr };
    PFN_xrDestroyOpaqueDataChannelNV pfn_destroy_{ nullptr };
    PFN_xrGetOpaqueDataChannelStateNV pfn_get_state_{ nullptr };
    PFN_xrReceiveOpaqueDataChannelNV pfn_receive_{ nullptr };
    PFN_xrShutdownOpaqueDataChannelNV pfn_shutdown_{ nullptr };

    std::optional<std::vector<uint8_t>> latest_message_;
    int64_t last_update_time_ = 0;
};

} // namespace core
