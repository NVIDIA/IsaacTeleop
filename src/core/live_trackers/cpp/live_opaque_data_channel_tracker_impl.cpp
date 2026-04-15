// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_opaque_data_channel_tracker_impl.hpp"

#include <deviceio_trackers/opaque_data_channel_tracker.hpp>
#include <oxr_utils/oxr_funcs.hpp>

#include <cstring>
#include <iostream>
#include <stdexcept>

namespace core
{

LiveOpaqueDataChannelTrackerImpl::LiveOpaqueDataChannelTrackerImpl(const OpenXRSessionHandles& handles,
                                                                   const OpaqueDataChannelTracker* tracker)
    : instance_(handles.instance)
{
    auto core_funcs = OpenXRCoreFunctions::load(handles.instance, handles.xrGetInstanceProcAddr);

    XrSystemId system_id;
    XrSystemGetInfo system_info{ XR_TYPE_SYSTEM_GET_INFO };
    system_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;

    XrResult result = core_funcs.xrGetSystem(handles.instance, &system_info, &system_id);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("[OpaqueDataChannel] Failed to get OpenXR system: " + std::to_string(result));
    }

    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrCreateOpaqueDataChannelNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_create_));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrDestroyOpaqueDataChannelNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_destroy_));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrGetOpaqueDataChannelStateNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_get_state_));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrReceiveOpaqueDataChannelNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_receive_));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrShutdownOpaqueDataChannelNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_shutdown_));

    XrOpaqueDataChannelCreateInfoNV create_info{};
    create_info.type = XR_TYPE_OPAQUE_DATA_CHANNEL_CREATE_INFO_NV;
    create_info.next = nullptr;
    create_info.systemId = system_id;

    const auto& uuid = tracker->get_uuid();
    static_assert(sizeof(create_info.uuid.data) == 16);
    std::memcpy(create_info.uuid.data, uuid.data(), 16);

    result = pfn_create_(handles.instance, &create_info, &channel_);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("[OpaqueDataChannel] xrCreateOpaqueDataChannelNV failed: " + std::to_string(result));
    }

    std::cout << "OpaqueDataChannelTracker initialized (channel created, waiting for connection)" << std::endl;
}

LiveOpaqueDataChannelTrackerImpl::~LiveOpaqueDataChannelTrackerImpl()
{
    if (channel_ != XR_NULL_HANDLE)
    {
        if (status_ == XR_OPAQUE_DATA_CHANNEL_STATUS_CONNECTED_NV)
        {
            pfn_shutdown_(channel_);
        }
        pfn_destroy_(channel_);
        channel_ = XR_NULL_HANDLE;
    }
}

void LiveOpaqueDataChannelTrackerImpl::update(int64_t monotonic_time_ns)
{
    last_update_time_ = monotonic_time_ns;
    latest_message_.reset();

    if (channel_ == XR_NULL_HANDLE)
    {
        return;
    }

    XrOpaqueDataChannelStateNV state{};
    state.type = XR_TYPE_OPAQUE_DATA_CHANNEL_STATE_NV;
    state.next = nullptr;

    XrResult result = pfn_get_state_(channel_, &state);
    if (XR_FAILED(result))
    {
        return;
    }
    status_ = state.state;

    if (status_ != XR_OPAQUE_DATA_CHANNEL_STATUS_CONNECTED_NV &&
        status_ != XR_OPAQUE_DATA_CHANNEL_STATUS_SHUTTING_NV)
    {
        return;
    }

    // Drain all queued messages, keeping only the latest.
    // xrReceiveOpaqueDataChannelNV dequeues one message per call.
    std::vector<uint8_t> buffer;
    while (true)
    {
        uint32_t byte_count = 0;
        result = pfn_receive_(channel_, 0, &byte_count, nullptr);
        if (result == XR_ERROR_CHANNEL_NOT_CONNECTED_NV || byte_count == 0)
        {
            break;
        }
        if (XR_FAILED(result))
        {
            break;
        }

        buffer.resize(byte_count);
        result = pfn_receive_(channel_, byte_count, &byte_count, buffer.data());
        if (XR_FAILED(result))
        {
            break;
        }

        latest_message_ = buffer;
    }
}

std::optional<std::vector<uint8_t>> LiveOpaqueDataChannelTrackerImpl::get_latest_message() const
{
    return latest_message_;
}

} // namespace core
