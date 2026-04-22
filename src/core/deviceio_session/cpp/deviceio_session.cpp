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
#include <unordered_map>

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
                        std::optional<McapRecordingConfig> mcap_config)
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
                    throw std::invalid_argument("LiveDeviceIOSession: McapRecordingConfig references tracker '" + name +
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

    const ITrackerImpl& get_tracker_impl(const ITracker& tracker) const override
    {
        auto it = tracker_impls_.find(&tracker);
        if (it == tracker_impls_.end())
        {
            throw std::runtime_error("Tracker implementation not found for tracker: " + std::string(tracker.get_name()));
        }
        return *(it->second);
    }

    void update() override
    {
        const int64_t monotonic_ns = os_monotonic_now_ns();
        for (auto& kv : tracker_impls_)
        {
            kv.second->update(monotonic_ns);
        }
    }

private:
    // mcap_writer_ declared before tracker_impls_ so impls (which may hold raw
    // pointers into the writer) are destroyed first in reverse declaration order.
    std::unique_ptr<mcap::McapWriter> mcap_writer_;
    std::unordered_map<const ITracker*, std::unique_ptr<ITrackerImpl>> tracker_impls_;
};

// ============================================================================
// ReplayDeviceIOSession (private)
// ============================================================================

class ReplayDeviceIOSession : public DeviceIOSession
{
public:
    explicit ReplayDeviceIOSession(const McapRecordingConfig& mcap_config)
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

    const ITrackerImpl& get_tracker_impl(const ITracker& tracker) const override
    {
        auto it = tracker_impls_.find(&tracker);
        if (it == tracker_impls_.end())
        {
            throw std::runtime_error("Tracker implementation not found for tracker: " + std::string(tracker.get_name()));
        }
        return *(it->second);
    }

    void update() override
    {
        const int64_t monotonic_ns = os_monotonic_now_ns();
        for (auto& kv : tracker_impls_)
        {
            kv.second->update(monotonic_ns);
        }
    }

private:
    // mcap_reader_ declared before tracker_impls_ so impls (which may hold raw
    // pointers into the reader) are destroyed first in reverse declaration order.
    std::unique_ptr<mcap::McapReader> mcap_reader_;
    std::unordered_map<const ITracker*, std::unique_ptr<ITrackerImpl>> tracker_impls_;
};

// ============================================================================
// DeviceIOSession (public API)
// ============================================================================

std::vector<std::string> DeviceIOSession::get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers)
{
    return LiveDeviceIOFactory::get_required_extensions(trackers);
}

std::unique_ptr<DeviceIOSession> DeviceIOSession::run(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                      const OpenXRSessionHandles& handles,
                                                      std::optional<McapRecordingConfig> mcap_config)
{
    assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
    assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
    assert(handles.space != XR_NULL_HANDLE && "OpenXR space handle cannot be null");

    std::cout << "DeviceIOSession: Creating live session with " << trackers.size() << " trackers" << std::endl;

    return std::make_unique<LiveDeviceIOSession>(trackers, handles, std::move(mcap_config));
}

std::unique_ptr<DeviceIOSession> DeviceIOSession::replay(const McapRecordingConfig& mcap_config)
{
    std::cout << "DeviceIOSession: Creating replay session with " << mcap_config.tracker_names.size() << " trackers"
              << std::endl;

    return std::make_unique<ReplayDeviceIOSession>(mcap_config);
}

} // namespace core
