#pragma once

#include "oxr_tracker.hpp"
#include <openxr/openxr.h>

namespace oxr {

// Head pose data
struct HeadPose {
    float position[3];      // x, y, z in meters
    float orientation[4];   // x, y, z, w (quaternion)
    bool is_valid;
    XrTime timestamp;
};

// Head tracker - tracks HMD pose
class HeadTracker : public ITracker {
public:
    HeadTracker();
    ~HeadTracker() override;
    
    // ITracker interface
    std::vector<std::string> get_required_extensions() const override;
    bool initialize(XrInstance instance, XrSession session, XrSpace base_space) override;
    bool update(XrTime time) override;
    bool is_initialized() const override { return initialized_; }
    std::string get_name() const override { return "HeadTracker"; }
    void cleanup() override;
    
    // Get head data
    const HeadPose& get_head() const { return head_; }

private:
    bool initialized_;
    XrSession session_;
    XrSpace base_space_;
    XrSpace view_space_;
    
    HeadPose head_;
};

} // namespace oxr


