// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/tracker.hpp>
#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>

#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

// Forward declaration -- mcap::McapWriter is an implementation detail of DeviceIOSession.
// Consumers of deviceio_core do not need to link against mcap::mcap.
namespace mcap
{
class McapWriter;
} // namespace mcap

namespace core
{

/**
 * @brief MCAP recording configuration for DeviceIOSession.
 *
 * tracker_names maps each ITracker pointer to its MCAP channel base name.
 * Trackers not in the map receive no channel writer and skip recording.
 * Pass as std::optional<McapRecordingConfig> to DeviceIOSession::run();
 * std::nullopt disables recording.
 */
struct McapRecordingConfig
{
    std::string filename;
    std::vector<std::pair<const ITracker*, std::string>> tracker_names;
};

// OpenXR DeviceIO Session - manages trackers and optional MCAP recording.
// When a McapRecordingConfig is provided, the session owns and drives a
// mcap::McapWriter; each tracker impl registers its own channels and writes
// directly during update().
class DeviceIOSession : public ITrackerSession
{
public:
    // Static helper — required OpenXR extensions for the given trackers (live factory; not per-tracker API).
    static std::vector<std::string> get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers);

    // Static factory - Create and initialize a session with trackers.
    // Optionally pass a McapRecordingConfig to enable automatic MCAP recording.
    static std::unique_ptr<DeviceIOSession> run(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                const OpenXRSessionHandles& handles,
                                                std::optional<McapRecordingConfig> recording_config = std::nullopt);

    // Destructor defined in .cpp where mcap::McapWriter is fully defined
    ~DeviceIOSession();

    // Update session and all trackers. If recording is active, tracker impls
    // write their data to the MCAP file directly during this call.
    void update();

    const ITrackerImpl& get_tracker_impl(const ITracker& tracker) const override
    {
        auto it = tracker_impls_.find(&tracker);
        if (it == tracker_impls_.end())
        {
            throw std::runtime_error("Tracker implementation not found for tracker: " + std::string(tracker.get_name()));
        }
        return *(it->second);
    }

private:
    DeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers,
                    const OpenXRSessionHandles& handles,
                    std::optional<McapRecordingConfig> recording_config);

    const OpenXRSessionHandles handles_;
    std::unordered_map<const ITracker*, std::unique_ptr<ITrackerImpl>> tracker_impls_;
    XrTimeConverter time_converter_;

    // Owned MCAP writer; null when recording is not configured.
    std::unique_ptr<mcap::McapWriter> mcap_writer_;
};

} // namespace core
