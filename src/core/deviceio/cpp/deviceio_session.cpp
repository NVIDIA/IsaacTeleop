// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/deviceio_session.hpp"

#include <cassert>
#include <iostream>
#include <set>
#include <stdexcept>
#include <unordered_set>

namespace core
{

// ============================================================================
// DeviceIOSession Implementation
// ============================================================================

DeviceIOSession::DeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                 const OpenXRSessionHandles& handles)
    : handles_(handles), time_converter_(handles)
{
    // Initialize all trackers and collect their implementations
    for (const auto& tracker : trackers)
    {
        tracker_impls_.emplace(tracker.get(), tracker->create_tracker(handles_));
    }
}

// Static helper - Get all required OpenXR extensions from a list of trackers
std::vector<std::string> DeviceIOSession::get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers)
{
    std::set<std::string> all_extensions;

    // Extensions required for XrTime conversion
    for (const auto& ext : XrTimeConverter::get_required_extensions())
    {
        all_extensions.insert(ext);
    }

    // Add extensions from each tracker
    for (const auto& tracker : trackers)
    {
        auto extensions = tracker->get_required_extensions();
        for (const auto& ext : extensions)
        {
            all_extensions.insert(ext);
        }
    }

    // Convert set to vector
    return std::vector<std::string>(all_extensions.begin(), all_extensions.end());
}

// Static factory - Create and initialize a session with trackers
std::unique_ptr<DeviceIOSession> DeviceIOSession::run(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                      const OpenXRSessionHandles& handles)
{
    // These should never be null - this is improper API usage
    assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
    assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
    assert(handles.space != XR_NULL_HANDLE && "OpenXR space handle cannot be null");

    std::cout << "DeviceIOSession: Creating session with " << trackers.size() << " trackers" << std::endl;

    // Constructor will throw on failure
    return std::unique_ptr<DeviceIOSession>(new DeviceIOSession(trackers, handles));
}

bool DeviceIOSession::update()
{
    XrTime current_time = time_converter_.os_monotonic_now();

    // Multiple ITracker instances may share the same ITrackerImpl (e.g. two
    // ControllerTrackers on the same XrSession).  Deduplicate so that each
    // unique impl is updated exactly once per frame.
    std::unordered_set<ITrackerImpl*> updated;

    for (auto& [tracker, impl] : tracker_impls_)
    {
        if (!updated.insert(impl.get()).second)
        {
            continue; // already updated this impl
        }

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
