#pragma once

#include "tracker.hpp"

#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_types.hpp>

#include <memory>
#include <string>
#include <time.h>
#include <vector>

// Define time conversion function pointer type if not in headers
typedef XrResult(XRAPI_PTR* PFN_xrConvertTimespecTimeToTimeKHR)(XrInstance instance,
                                                                const struct timespec* timespecTime,
                                                                XrTime* time);

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
    PFN_xrConvertTimespecTimeToTimeKHR pfn_convert_timespec_;

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
