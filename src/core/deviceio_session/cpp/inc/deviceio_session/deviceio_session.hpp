// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>

#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mcap
{
class McapWriter;
} // namespace mcap

namespace core
{

/**
 * @brief MCAP configuration for recording (live) and replay sessions.
 *
 * filename: path to the MCAP file (written by live, read by replay).
 * tracker_names maps each ITracker pointer to its MCAP channel base name.
 *
 * Lifetime: the ITracker pointers in tracker_names must remain valid for the
 * lifetime of the DeviceIOSession created from this config, because the session
 * stores them as map keys for get_tracker_impl() lookups. For live sessions,
 * this is naturally satisfied by the shared_ptr<ITracker> vector passed to
 * createLiveSession. For replay sessions, the caller must keep the tracker
 * objects alive until the session is destroyed.
 *
 * Live: trackers not in the map skip recording; the map is optional.
 * Replay: tracker_names is the sole source of tracker-to-channel mapping.
 */
struct McapConfig
{
    std::string filename;
    std::vector<std::pair<const ITracker*, std::string>> tracker_names;
};

// DeviceIO Session — manages tracker implementations and drives the update loop.
// Concrete resource ownership (McapWriter for live, McapReader for replay) lives
// in private subclasses; only the DeviceIOSession API is public.
class DeviceIOSession : public ITrackerSession
{
public:
    /// Aggregate OpenXR extensions required for a live session with these trackers.
    static std::vector<std::string> get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers);
    // Static factory - Create and initialize a session with trackers.
    // Optionally pass a McapConfig to enable automatic MCAP recording.
    static std::unique_ptr<DeviceIOSession> createLiveSession(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                              const OpenXRSessionHandles& handles,
                                                              std::optional<McapConfig> mcap_config = std::nullopt);

    /// Create a replay session that reads recorded data from an MCAP file.
    /// Opens mcap_config.filename and uses mcap_config.tracker_names
    /// to map trackers to MCAP channels.
    static std::unique_ptr<DeviceIOSession> createReplaySession(const McapConfig& mcap_config);

    ~DeviceIOSession() override;


    /**
     * @brief Updates the session and all registered trackers.
     *
     * If recording is active, tracker implementations write MCAP samples
     * directly during this call.
     *
     * @throws std::runtime_error On critical tracker/runtime failures.
     * @note A thrown exception indicates a fatal condition; the application is
     *       expected to terminate rather than continue running.
     */
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

protected:
    DeviceIOSession() = default;

    // INVARIANT: derived classes that own an MCAP resource (writer/reader) MUST
    // clear tracker_impls_ in their destructor, because C++ destroys derived
    // members before base members and the impls may hold raw pointers into the
    // derived-owned resource.
    std::unordered_map<const ITracker*, std::unique_ptr<ITrackerImpl>> tracker_impls_;
};

} // namespace core
