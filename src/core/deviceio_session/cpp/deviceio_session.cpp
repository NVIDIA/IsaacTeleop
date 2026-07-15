// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_session/deviceio_session.hpp"

#include <live_trackers/live_deviceio_factory.hpp>
#include <mcap/writer.hpp>
#include <openxr/openxr.h>
#include <oxr_utils/os_time.hpp>

#include <cassert>
#include <iostream>
#include <stdexcept>

namespace core
{

// ============================================================================
// DeviceIOSession Implementation
// ============================================================================

namespace
{

bool tracker_in_list(const std::vector<std::shared_ptr<ITracker>>& trackers, const ITracker* tracker_ptr)
{
    for (const auto& t : trackers)
    {
        if (t.get() == tracker_ptr)
            return true;
    }
    return false;
}

} // namespace

DeviceIOSession::DeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                 const OpenXRSessionHandles& handles,
                                 std::optional<McapRecordingConfig> recording_config,
                                 VendorConfig vendor_config)
    : handles_(handles)
{
    std::vector<std::pair<const ITracker*, std::string>> tracker_names;

    for (const auto& [tracker_ptr, vendor] : vendor_config.tracker_vendors)
    {
        if (!tracker_in_list(trackers, tracker_ptr))
        {
            throw std::invalid_argument("DeviceIOSession: VendorConfig references tracker with vendor id '" +
                                        vendor.id + "' that is not in the session's tracker list");
        }
    }

    if (recording_config)
    {
        for (const auto& [tracker_ptr, name] : recording_config->tracker_names)
        {
            if (!tracker_in_list(trackers, tracker_ptr))
            {
                throw std::invalid_argument("DeviceIOSession: McapRecordingConfig references tracker '" + name +
                                            "' that is not in the session's tracker list");
            }
        }

        mcap_writer_ = std::make_unique<mcap::McapWriter>();
        mcap::McapWriterOptions options("teleop");
        options.compression = mcap::Compression::None;

        auto status = mcap_writer_->open(recording_config->filename, options);
        if (!status.ok())
        {
            throw std::runtime_error("DeviceIOSession: failed to open MCAP file '" + recording_config->filename +
                                     "': " + status.message);
        }
        std::cout << "DeviceIOSession: recording to " << recording_config->filename << std::endl;

        tracker_names = std::move(recording_config->tracker_names);
    }

    LiveDeviceIOFactory factory(handles_, mcap_writer_.get(), tracker_names, vendor_config.tracker_vendors);

    for (const auto& tracker : trackers)
    {
        if (!tracker)
        {
            throw std::invalid_argument("DeviceIOSession: null tracker in trackers list");
        }
        tracker_impls_.emplace(tracker.get(), factory.create_tracker_impl(*tracker));
    }
}

DeviceIOSession::~DeviceIOSession() = default;

std::vector<std::string> DeviceIOSession::get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                                  const VendorConfig& vendor_config)
{
    return LiveDeviceIOFactory::get_required_extensions(trackers, vendor_config.tracker_vendors);
}

std::unique_ptr<DeviceIOSession> DeviceIOSession::run(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                      const OpenXRSessionHandles& handles,
                                                      std::optional<McapRecordingConfig> recording_config,
                                                      VendorConfig vendor_config)
{
    assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
    assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
    assert(handles.space != XR_NULL_HANDLE && "OpenXR space handle cannot be null");

    std::cout << "DeviceIOSession: Creating session with " << trackers.size() << " trackers" << std::endl;

    return std::unique_ptr<DeviceIOSession>(
        new DeviceIOSession(trackers, handles, std::move(recording_config), std::move(vendor_config)));
}

void DeviceIOSession::update()
{
    const int64_t monotonic_ns = os_monotonic_now_ns();

    for (auto& kv : tracker_impls_)
    {
        kv.second->update(monotonic_ns);
    }
}

} // namespace core
