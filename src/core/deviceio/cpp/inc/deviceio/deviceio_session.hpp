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

// Forward declarations
class McapRecorder;

// OpenXR DeviceIO Session - Main user-facing class for OpenXR tracking
// Manages trackers and session lifetime
class DeviceIOSession
{
public:
    ~DeviceIOSession();

    // Explicitly delete copy constructor and copy assignment (non-copyable due to unique_ptr members)
    DeviceIOSession(const DeviceIOSession&) = delete;
    DeviceIOSession& operator=(const DeviceIOSession&) = delete;

    // Static helper - Get all required OpenXR extensions from a list of trackers
    static std::vector<std::string> get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers);

    // Static factory - Create and initialize a session with trackers
    // Returns fully initialized session ready to use (throws on failure)
    // If mcap_recording_path is non-empty, MCAP recording will be started automatically
    static std::unique_ptr<DeviceIOSession> run(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                const OpenXRSessionHandles& handles,
                                                const std::string& mcap_recording_path = "");

    // Update session and all trackers (auto-records if recording is enabled)
    bool update();

private:
    // Private constructor - use run() instead (throws std::runtime_error on failure)
    DeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers, const OpenXRSessionHandles& handles);

    OpenXRSessionHandles handles_;
    std::vector<std::shared_ptr<ITrackerImpl>> tracker_impls_; // Actual implementations

    // For time conversion
#if defined(XR_USE_PLATFORM_WIN32)
    PFN_xrConvertWin32PerformanceCounterToTimeKHR pfn_convert_win32_{};
#elif defined(XR_USE_TIMESPEC)
    PFN_xrConvertTimespecTimeToTimeKHR pfn_convert_timespec_{};
#endif

    // MCAP recording
    std::unique_ptr<McapRecorder> recorder_;
    bool start_recording(const std::string& filename);
    void stop_recording();
    bool is_recording() const;
};

} // namespace core
