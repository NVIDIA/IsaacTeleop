// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/deviceio_session.hpp"

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
    XrTime current_time = time_converter_.get_current_time();

    // Update all tracker implementations directly
    for (auto& impl : tracker_impls_)
    {
        if (!impl.second->update(current_time))
        {
            // Rate-limit warnings to avoid log spam (log first failure, then every 1000th)
            auto& count = tracker_update_failure_counts_[impl.first];
            count++;
            if (count == 1 || count % 1000 == 0)
            {
                std::cerr << "Warning: tracker '" << impl.first->get_name() << "' update failed (count: " << count
                          << ")" << std::endl;
            }
        }
        else
        {
            // Reset count on success
            tracker_update_failure_counts_[impl.first] = 0;
        }
    }

    return true;
}

} // namespace core
