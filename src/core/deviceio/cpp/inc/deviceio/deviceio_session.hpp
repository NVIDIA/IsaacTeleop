// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_types.hpp>

// Include platform-specific headers first
#if defined(XR_USE_PLATFORM_WIN32)
#    include <windows.h>
#elif defined(XR_USE_TIMESPEC)
#    include <time.h>
#endif
// Include OpenXR platform header after platform-specific includes
#include <openxr/openxr_platform.h>

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

    // Get tracker implementation for a given tracker (for use by McapRecorder)
    const ITrackerImpl& get_tracker_impl(const ITracker& tracker) const
    {
        auto it = tracker_impls_.find(&tracker);
        if (it == tracker_impls_.end())
        {
            throw std::runtime_error("Tracker implementation not found for tracker: " + tracker.get_name());
        }
        return *(it->second);
    }

private:
    // Private constructor - use run() instead (throws std::runtime_error on failure)
    DeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers, const OpenXRSessionHandles& handles);

    const OpenXRSessionHandles handles_;
    std::unordered_map<const ITracker*, std::shared_ptr<ITrackerImpl>> tracker_impls_;

    // For time conversion
#if defined(XR_USE_PLATFORM_WIN32)
    PFN_xrConvertWin32PerformanceCounterToTimeKHR pfn_convert_win32_{};
#elif defined(XR_USE_TIMESPEC)
    PFN_xrConvertTimespecTimeToTimeKHR pfn_convert_timespec_{};
#endif
};

} // namespace core
