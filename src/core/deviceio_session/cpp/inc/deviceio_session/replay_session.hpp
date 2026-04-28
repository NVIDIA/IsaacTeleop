// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/tracker.hpp>

#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace core
{

/**
 * @brief MCAP replay configuration for ReplaySession.
 *
 * filename: path to the MCAP file to read.
 * tracker_names: maps each ITracker pointer to its MCAP channel base name.
 * This is the sole source of tracker-to-channel mapping for replay.
 *
 * Lifetime: the ITracker pointers must remain valid for the lifetime of the
 * ReplaySession, because the session stores them as map keys for
 * get_tracker_impl() lookups.
 */
struct McapReplayConfig
{
    std::string filename;
    std::vector<std::pair<const ITracker*, std::string>> tracker_names;
};

// Replay session — reads recorded tracker data from an MCAP file.
class ReplaySession : public ITrackerSession
{
public:
    // Static factory - Open an MCAP file and create replay tracker implementations.
    static std::unique_ptr<ReplaySession> run(const McapReplayConfig& config);

    /**
     * @brief Advances replay by one frame, feeding the next recorded sample to
     *        each tracker implementation.
     *
     * @throws std::runtime_error On critical replay failures.
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

private:
    explicit ReplaySession(const McapReplayConfig& config);

    std::unordered_map<const ITracker*, std::unique_ptr<ITrackerImpl>> tracker_impls_;
};

} // namespace core
