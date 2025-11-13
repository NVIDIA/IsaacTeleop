// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/xrio/teleop_session.hpp"

#include <cassert>
#include <iostream>
#include <set>
#include <time.h>

namespace oxr
{

// ============================================================================
// TeleopSession Implementation
// ============================================================================

// Static factory method - Create with session handles
std::shared_ptr<TeleopSession> TeleopSession::Create(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                     const OpenXRSessionHandles& handles)
{

    auto session = std::shared_ptr<TeleopSession>(new TeleopSession(handles));

    if (!session->initialize(trackers))
    {
        return nullptr;
    }

    return session;
}

// Private constructor - Create with session handles
TeleopSession::TeleopSession(const OpenXRSessionHandles& handles) : handles_(handles), pfn_convert_timespec_(nullptr)
{

    // These should never be null - this is improper API usage
    assert(handles_.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
    assert(handles_.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
    assert(handles_.space != XR_NULL_HANDLE && "OpenXR space handle cannot be null");

    std::cout << "TeleopSession: Creating session with OpenXR handles" << std::endl;

    // Get time conversion function using the provided xrGetInstanceProcAddr
    if (handles_.xrGetInstanceProcAddr)
    {
        handles_.xrGetInstanceProcAddr(handles_.instance, "xrConvertTimespecTimeToTimeKHR",
                                       reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert_timespec_));

        if (!pfn_convert_timespec_)
        {
            std::cerr << "Warning: xrConvertTimespecTimeToTimeKHR not available" << std::endl;
        }
    }
    else
    {
        std::cerr << "Error: xrGetInstanceProcAddr is null in session handles" << std::endl;
    }
}

TeleopSession::~TeleopSession()
{
    // RAII cleanup - impls will be destroyed automatically
    tracker_impls_.clear();
}

bool TeleopSession::initialize(const std::vector<std::shared_ptr<ITracker>>& trackers)
{
    if (handles_.instance == XR_NULL_HANDLE)
    {
        std::cerr << "TeleopSession: No valid OpenXR handles" << std::endl;
        return false;
    }

    // Initialize all trackers and collect their implementations
    for (const auto& tracker : trackers)
    {
        auto impl = tracker->initialize(handles_);
        if (!impl)
        {
            std::cerr << "Failed to initialize tracker: " << tracker->get_name() << std::endl;
            return false;
        }
        tracker_impls_.push_back(std::move(impl));
    }

    std::cout << "TeleopSession: Initialized " << tracker_impls_.size() << " trackers" << std::endl;
    return true;
}

bool TeleopSession::update()
{
    // Get current time
    XrTime current_time;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);

    if (pfn_convert_timespec_)
    {
        pfn_convert_timespec_(handles_.instance, &ts, &current_time);
    }
    else
    {
        std::cerr << "Cannot get time - time conversion not available" << std::endl;
        return false;
    }

    // Update all tracker implementations directly
    for (auto& impl : tracker_impls_)
    {
        if (!impl->update(current_time))
        {
            std::cerr << "Warning: tracker update failed" << std::endl;
        }
    }

    return true;
}

// ============================================================================
// TeleopSessionBuilder Implementation
// ============================================================================

TeleopSessionBuilder::TeleopSessionBuilder()
{
}

TeleopSessionBuilder::~TeleopSessionBuilder()
{
}

void TeleopSessionBuilder::add_tracker(std::shared_ptr<ITracker> tracker)
{
    trackers_.push_back(tracker);
}

std::vector<std::string> TeleopSessionBuilder::get_required_extensions() const
{
    std::set<std::string> all_extensions;

    // Required for getting the time without a frame loop
    all_extensions.insert("XR_KHR_convert_timespec_time");

    // Add extensions from each tracker
    for (const auto& tracker : trackers_)
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

std::shared_ptr<TeleopSession> TeleopSessionBuilder::build(const OpenXRSessionHandles& handles)
{

    // These should never be null - this is improper API usage
    assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
    assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
    assert(handles.space != XR_NULL_HANDLE && "OpenXR space handle cannot be null");

    std::cout << "TeleopSessionBuilder: Building teleop session with " << trackers_.size() << " trackers" << std::endl;

    // Build teleop session with the provided handles
    return TeleopSession::Create(trackers_, handles);
}

} // namespace oxr
