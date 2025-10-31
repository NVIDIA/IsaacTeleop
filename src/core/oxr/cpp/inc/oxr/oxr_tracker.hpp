#pragma once

#include <openxr/openxr.h>
#include <string>
#include <vector>

namespace oxr {

// Base interface for all trackers
class ITracker {
public:
    virtual ~ITracker() = default;
    
    // Get required OpenXR extensions for this tracker
    virtual std::vector<std::string> get_required_extensions() const = 0;
    
    // Initialize tracker (called after session is created)
    virtual bool initialize(XrInstance instance, XrSession session, XrSpace base_space) = 0;
    
    // Update tracker data with current time
    virtual bool update(XrTime time) = 0;
    
    // Check if initialized
    virtual bool is_initialized() const = 0;
    
    // Get tracker name for debugging
    virtual std::string get_name() const = 0;
    
    // Cleanup tracker resources (called before session/instance destruction)
    virtual void cleanup() = 0;
};

} // namespace oxr


