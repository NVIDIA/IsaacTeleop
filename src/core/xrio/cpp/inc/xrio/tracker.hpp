#pragma once

#include <openxr/openxr.h>
#include <string>
#include <vector>
#include <memory>

namespace oxr {

// Forward declare friend classes that can access internal lifecycle methods
class TeleopSession;

// Base interface for tracker implementations
// These are the actual worker objects that get updated by the session
class ITrackerImpl {
public:
    virtual ~ITrackerImpl() = default;
    
    // Update the tracker with the current time
    virtual bool update(XrTime time) = 0;
};

// Base interface for all trackers
// PUBLIC API: Only exposes methods that external users should call
// Trackers are responsible for initialization and creating their impl
class ITracker {
public:
    virtual ~ITracker() = default;
    
    // Public API - visible to all users
    virtual std::vector<std::string> get_required_extensions() const = 0;
    virtual std::string get_name() const = 0;
    virtual bool is_initialized() const = 0;
    
protected:
    // Internal lifecycle methods - only accessible to friend classes
    // External users should NOT call these directly
    friend class TeleopSession;
    
    // Initialize the tracker and return its implementation
    // Returns nullptr on failure
    virtual std::shared_ptr<ITrackerImpl> initialize(XrInstance instance, XrSession session, XrSpace base_space) = 0;
};

} // namespace oxr


