// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/deviceio_session.hpp"

#include <cassert>
#include <cstdlib>
#include <iostream>
#include <mcap_recorder.hpp>
#include <set>
#include <stdexcept>
#include <time.h>

namespace core
{

// ============================================================================
// DeviceIOSession Implementation
// ============================================================================

DeviceIOSession::DeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                 const OpenXRSessionHandles& handles)
    : handles_(handles)
{
    // Get time conversion function using the provided xrGetInstanceProcAddr
    assert(handles_.xrGetInstanceProcAddr && "xrGetInstanceProcAddr cannot be null");

#if defined(XR_USE_PLATFORM_WIN32)
    handles_.xrGetInstanceProcAddr(handles_.instance, "xrConvertWin32PerformanceCounterToTimeKHR",
                                   reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert_win32_));
    if (!pfn_convert_win32_)
    {
        throw std::runtime_error("xrConvertWin32PerformanceCounterToTimeKHR not available");
    }
#elif defined(XR_USE_TIMESPEC)
    handles_.xrGetInstanceProcAddr(handles_.instance, "xrConvertTimespecTimeToTimeKHR",
                                   reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert_timespec_));

    if (!pfn_convert_timespec_)
    {
        throw std::runtime_error("xrConvertTimespecTimeToTimeKHR not available");
    }
#endif

    // Initialize all trackers and collect their implementations
    for (const auto& tracker : trackers)
    {
        auto impl = tracker->initialize(handles_);
        if (!impl)
        {
            throw std::runtime_error("Failed to initialize tracker: " + tracker->get_name());
        }
        tracker_impls_.push_back(std::move(impl));
    }

    std::cout << "DeviceIOSession: Initialized " << tracker_impls_.size() << " trackers" << std::endl;

    // Check if MCAP recording is enabled via environment variable
    const char* mcap_recording = std::getenv("MCAP_RECORDING");
    if (mcap_recording != nullptr && std::string(mcap_recording) != "")
    {
        if (!start_recording(mcap_recording))
        {
            std::cerr << "DeviceIOSession: Warning - Failed to start MCAP recording to " << mcap_recording << std::endl;
        }
    }
}

DeviceIOSession::~DeviceIOSession()
{
    // Stop recording if active
    stop_recording();

    // RAII cleanup - impls will be destroyed automatically
}

// Static helper - Get all required OpenXR extensions from a list of trackers
std::vector<std::string> DeviceIOSession::get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers)
{
    std::set<std::string> all_extensions;

    // Required for getting the time without a frame loop
#if defined(XR_USE_PLATFORM_WIN32)
    all_extensions.insert(XR_KHR_WIN32_CONVERT_PERFORMANCE_COUNTER_TIME_EXTENSION_NAME);
#else
    all_extensions.insert(XR_KHR_CONVERT_TIMESPEC_TIME_EXTENSION_NAME);
#endif

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
    // Get current time
    XrTime current_time;
#if defined(XR_USE_PLATFORM_WIN32)
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);

    if (pfn_convert_win32_)
    {
        pfn_convert_win32_(handles_.instance, &counter, &current_time);
    }
    else
    {
        std::cerr << "Cannot get time - time conversion not available" << std::endl;
        return false;
    }
#elif defined(XR_USE_TIMESPEC)
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
#endif

    // Update all tracker implementations directly
    for (auto& impl : tracker_impls_)
    {
        if (!impl->update(current_time))
        {
            std::cerr << "Warning: tracker update failed" << std::endl;
        }
    }

    // Record tracker data if recording is enabled
    record_tracker_data();

    return true;
}

// ============================================================================
// MCAP Recording Implementation
// ============================================================================

bool DeviceIOSession::start_recording(const std::string& filename)
{
    if (recorder_ && recorder_->is_open())
    {
        std::cerr << "DeviceIOSession: Recording already in progress" << std::endl;
        return false;
    }

    recorder_ = std::make_unique<McapRecorder>();
    if (!recorder_->open(filename))
    {
        recorder_.reset();
        return false;
    }

    // Register all trackers with the recorder
    for (const auto& impl : tracker_impls_)
    {
        recorder_->add_tracker(impl);
    }

    std::cout << "DeviceIOSession: Started recording to " << filename << std::endl;
    return true;
}

void DeviceIOSession::stop_recording()
{
    if (recorder_)
    {
        recorder_->close();
        recorder_.reset();
    }
}

bool DeviceIOSession::is_recording() const
{
    return recorder_ && recorder_->is_open();
}

void DeviceIOSession::record_tracker_data()
{
    if (!is_recording())
    {
        return;
    }

    for (const auto& impl : tracker_impls_)
    {
        recorder_->record(impl);
    }
}

} // namespace core
