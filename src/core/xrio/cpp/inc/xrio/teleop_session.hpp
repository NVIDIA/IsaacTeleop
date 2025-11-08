// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_types.hpp>

// Include platform-specific headers first
#if defined(XR_USE_PLATFORM_WIN32)
#include <windows.h>
#elif defined(XR_USE_TIMESPEC)
#include <time.h>
#endif
// Include OpenXR platform header after platform-specific includes
#include <openxr/openxr_platform.h>

#include <memory>
#include <string>
#include <vector>

namespace oxr
{

// OpenXR Teleop Session - Main user-facing class for OpenXR tracking
// Always uses handles from external session - user manages session lifetime
class TeleopSession
{
public:
    ~TeleopSession();

    // Explicitly delete copy constructor and copy assignment (non-copyable due to unique_ptr members)
    TeleopSession(const TeleopSession&) = delete;
    TeleopSession& operator=(const TeleopSession&) = delete;

    // Static factory method - return nullptr on failure
    // Create session with OpenXR session handles
    static std::shared_ptr<TeleopSession> Create(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                 const OpenXRSessionHandles& handles);

    // Update session and all trackers
    bool update();

private:
    // Private constructor - use Create() instead
    TeleopSession(const OpenXRSessionHandles& handles);

    OpenXRSessionHandles handles_;
    std::vector<std::shared_ptr<ITrackerImpl>> tracker_impls_; // Actual implementations

    // For time conversion
#if defined(XR_USE_PLATFORM_WIN32)
    PFN_xrConvertWin32PerformanceCounterToTimeKHR pfn_convert_win32_{};
#elif defined(XR_USE_TIMESPEC)
    PFN_xrConvertTimespecTimeToTimeKHR pfn_convert_timespec_{};
#endif

    // Initialization logic
    bool initialize(const std::vector<std::shared_ptr<ITracker>>& trackers);
};

// OpenXR Teleop Session Builder - Helps construct teleop sessions with trackers
// Builder pattern for convenience when managing multiple trackers
class TeleopSessionBuilder
{
public:
    TeleopSessionBuilder();
    ~TeleopSessionBuilder();

    // Add a tracker to the builder
    void add_tracker(std::shared_ptr<ITracker> tracker);

    // Get all required extensions from the trackers
    std::vector<std::string> get_required_extensions() const;

    // Build a teleop session with OpenXR session handles
    std::shared_ptr<TeleopSession> build(const OpenXRSessionHandles& handles);

private:
    std::vector<std::shared_ptr<ITracker>> trackers_;
};

} // namespace oxr
