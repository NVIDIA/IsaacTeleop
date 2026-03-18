// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// MCAP_IMPLEMENTATION must be defined in exactly one translation unit that
// includes <mcap/writer.hpp>. All other TUs get declarations only.
#define MCAP_IMPLEMENTATION

#include "inc/deviceio_session/deviceio_session.hpp"

#include <deviceio_base/tracker_factory.hpp>
#include <live_trackers/live_deviceio_factory.hpp>
#include <mcap/writer.hpp>

#include <cassert>
#include <iostream>
#include <set>
#include <stdexcept>

namespace core
{

// ============================================================================
// DeviceIOSession Implementation
// ============================================================================

DeviceIOSession::DeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                 const OpenXRSessionHandles& handles,
                                 std::optional<McapRecordingConfig> recording_config)
    : handles_(handles), time_converter_(handles)
{
    std::vector<std::pair<const ITracker*, std::string>> tracker_names;

    if (recording_config)
    {
        for (const auto& [tracker_ptr, name] : recording_config->tracker_names)
        {
            bool found = false;
            for (const auto& t : trackers)
            {
                if (t.get() == tracker_ptr)
                {
                    found = true;
                    break;
                }
            }
            if (!found)
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

    LiveDeviceIOFactory factory(handles_, mcap_writer_.get(), tracker_names);

    for (const auto& tracker : trackers)
    {
        if (!tracker)
        {
            throw std::invalid_argument("DeviceIOSession: null tracker in trackers list");
        }
        auto impl = tracker->create_tracker_impl(factory);
        if (!impl)
        {
            throw std::runtime_error("DeviceIOSession: tracker '" + std::string(tracker->get_name()) +
                                     "' returned null impl");
        }
        tracker_impls_.emplace(tracker.get(), std::move(impl));
    }
}

DeviceIOSession::~DeviceIOSession() = default;

std::vector<std::string> DeviceIOSession::get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers)
{
    std::set<std::string> all_extensions;

    for (const auto& ext : XrTimeConverter::get_required_extensions())
    {
        all_extensions.insert(ext);
    }

    for (const auto& tracker : trackers)
    {
        if (!tracker)
        {
            throw std::invalid_argument("DeviceIOSession: null tracker in trackers list");
        }
        auto extensions = tracker->get_required_extensions();
        for (const auto& ext : extensions)
        {
            all_extensions.insert(ext);
        }
    }

    return std::vector<std::string>(all_extensions.begin(), all_extensions.end());
}

std::unique_ptr<DeviceIOSession> DeviceIOSession::run(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                      const OpenXRSessionHandles& handles,
                                                      std::optional<McapRecordingConfig> recording_config)
{
    assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
    assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
    assert(handles.space != XR_NULL_HANDLE && "OpenXR space handle cannot be null");

    std::cout << "DeviceIOSession: Creating session with " << trackers.size() << " trackers" << std::endl;

    return std::unique_ptr<DeviceIOSession>(new DeviceIOSession(trackers, handles, std::move(recording_config)));
}

bool DeviceIOSession::update()
{
    XrTime current_time = time_converter_.os_monotonic_now();

    for (auto& [tracker, impl] : tracker_impls_)
    {
        if (!impl->update(current_time))
        {
            auto& count = tracker_update_failure_counts_[tracker];
            count++;
            if (count == 1 || count % 1000 == 0)
            {
                std::cerr << "Warning: tracker '" << tracker->get_name() << "' update failed (count: " << count << ")"
                          << std::endl;
            }
        }
        else
        {
            tracker_update_failure_counts_[tracker] = 0;
        }
    }

    return true;
}

} // namespace core
