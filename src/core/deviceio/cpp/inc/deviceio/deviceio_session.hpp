// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>

#include <memory>
#include <string>
#include <vector>

namespace core
{

// OpenXR DeviceIO Session - Main user-facing class for OpenXR tracking
// Manages trackers and session lifetime
class DeviceIOSession
{
public:
    // Static helper - Get all required OpenXR extensions from a list of trackers
    static std::vector<std::string> get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers);

    // Static factory - Create and initialize a session with trackers
    // Returns fully initialized session ready to use (throws on failure)
    static std::unique_ptr<DeviceIOSession> run(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                const OpenXRSessionHandles& handles);

    // Update session and all trackers
    bool update();

    const ITrackerImpl& get_tracker_impl(const ITracker& tracker) const
    {
        auto it = tracker_impls_.find(&tracker);
        if (it == tracker_impls_.end())
        {
            throw std::runtime_error("Tracker implementation not found for tracker: " + std::string(tracker.get_name()));
        }
        return *(it->second);
    }

private:
    // Private constructor - use run() instead (throws std::runtime_error on failure)
    DeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers, const OpenXRSessionHandles& handles);

    const OpenXRSessionHandles handles_;
    std::unordered_map<const ITracker*, std::shared_ptr<ITrackerImpl>> tracker_impls_;
    std::unordered_map<const ITracker*, uint64_t> tracker_update_failure_counts_;

    // For time conversion
    XrTimeConverter time_converter_;
};

} // namespace core
