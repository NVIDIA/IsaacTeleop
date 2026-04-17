// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// MCAP_IMPLEMENTATION must be defined in exactly one translation unit that
// includes <mcap/writer.hpp>. All other TUs get declarations only.
#define MCAP_IMPLEMENTATION

#include "inc/deviceio_session/deviceio_session.hpp"

#include <live_trackers/live_deviceio_factory.hpp>
#include <mcap/reader.hpp>
#include <mcap/writer.hpp>
#include <openxr/openxr.h>
#include <oxr_utils/os_time.hpp>
#include <replay_trackers/replay_deviceio_factory.hpp>

#include <cassert>
#include <iostream>
#include <stdexcept>

namespace core
{

// ============================================================================
// LiveDeviceIOSession (private)
// ============================================================================

class LiveDeviceIOSession : public DeviceIOSession
{
public:
    LiveDeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers,
                        const OpenXRSessionHandles& handles,
                        std::optional<McapConfig> mcap_config)
    {
        std::vector<std::pair<const ITracker*, std::string>> tracker_names;

        if (mcap_config)
        {
            for (const auto& [tracker_ptr, name] : mcap_config->tracker_names)
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
                    throw std::invalid_argument("LiveDeviceIOSession: McapConfig references tracker '" + name +
                                                "' that is not in the session's tracker list");
                }
            }

            mcap_writer_ = std::make_unique<mcap::McapWriter>();
            mcap::McapWriterOptions options("teleop");
            options.compression = mcap::Compression::None;

            auto status = mcap_writer_->open(mcap_config->filename, options);
            if (!status.ok())
            {
                throw std::runtime_error("LiveDeviceIOSession: failed to open MCAP file '" + mcap_config->filename +
                                         "': " + status.message);
            }
            std::cout << "LiveDeviceIOSession: recording to " << mcap_config->filename << std::endl;

            tracker_names = std::move(mcap_config->tracker_names);
        }

        LiveDeviceIOFactory factory(handles, mcap_writer_.get(), tracker_names);
        for (const auto& tracker : trackers)
        {
            if (!tracker)
            {
                throw std::invalid_argument("LiveDeviceIOSession: null tracker in trackers list");
            }
            auto impl = factory.create_tracker_impl(*tracker);
            if (!impl)
            {
                throw std::runtime_error("LiveDeviceIOSession: tracker '" + std::string(tracker->get_name()) +
                                         "' returned null impl");
            }
            tracker_impls_.emplace(tracker.get(), std::move(impl));
        }
    }

    // Ensure tracker impls (which hold raw McapWriter pointers) are destroyed
    // before the writer they reference.
    ~LiveDeviceIOSession() override
    {
        tracker_impls_.clear();
    }

private:
    std::unique_ptr<mcap::McapWriter> mcap_writer_;
};

// ============================================================================
// ReplayDeviceIOSession (private)
// ============================================================================

class ReplayDeviceIOSession : public DeviceIOSession
{
public:
    explicit ReplayDeviceIOSession(const McapConfig& mcap_config)
    {
        mcap_reader_ = std::make_unique<mcap::McapReader>();
        auto status = mcap_reader_->open(mcap_config.filename);
        if (!status.ok())
        {
            throw std::runtime_error("ReplayDeviceIOSession: failed to open MCAP file '" + mcap_config.filename +
                                     "': " + status.message);
        }
        std::cout << "ReplayDeviceIOSession: reading from " << mcap_config.filename << std::endl;

        ReplayDeviceIOFactory factory(*mcap_reader_, mcap_config.tracker_names);
        for (const auto& [tracker_ptr, name] : mcap_config.tracker_names)
        {
            auto impl = factory.create_tracker_impl(*tracker_ptr);
            if (!impl)
            {
                throw std::runtime_error("ReplayDeviceIOSession: tracker '" + name + "' returned null impl");
            }
            tracker_impls_.emplace(tracker_ptr, std::move(impl));
        }
    }

    ~ReplayDeviceIOSession() override
    {
        tracker_impls_.clear();
    }

private:
    std::unique_ptr<mcap::McapReader> mcap_reader_;
};

// ============================================================================
// DeviceIOSession (public API)
// ============================================================================

DeviceIOSession::~DeviceIOSession() = default;

std::vector<std::string> DeviceIOSession::get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers)
{
    return LiveDeviceIOFactory::get_required_extensions(trackers);
}

std::unique_ptr<DeviceIOSession> DeviceIOSession::createLiveSession(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                                    const OpenXRSessionHandles& handles,
                                                                    std::optional<McapConfig> mcap_config)
{
    assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
    assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
    assert(handles.space != XR_NULL_HANDLE && "OpenXR space handle cannot be null");

    std::cout << "DeviceIOSession: Creating live session with " << trackers.size() << " trackers" << std::endl;

    return std::make_unique<LiveDeviceIOSession>(trackers, handles, std::move(mcap_config));
}

std::unique_ptr<DeviceIOSession> DeviceIOSession::createReplaySession(const McapConfig& mcap_config)
{
    std::cout << "DeviceIOSession: Creating replay session with " << mcap_config.tracker_names.size() << " trackers"
              << std::endl;

    return std::make_unique<ReplayDeviceIOSession>(mcap_config);
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
