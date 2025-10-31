#pragma once

#include "oxr_tracker.hpp"
#include <openxr/openxr.h>
#include <array>

namespace oxr {

// Hand joint data structure
struct JointPose {
    float position[3];      // x, y, z in meters
    float orientation[4];   // x, y, z, w (quaternion)
    float radius;
    bool is_valid;
};

// Hand tracking data for a single hand
struct HandData {
    static constexpr size_t NUM_JOINTS = 26;  // XR_HAND_JOINT_COUNT_EXT
    std::array<JointPose, NUM_JOINTS> joints;
    bool is_active;
    XrTime timestamp;
};

// Hand tracker - tracks both left and right hands
class HandTracker : public ITracker {
public:
    HandTracker();
    ~HandTracker() override;
    
    // ITracker interface
    std::vector<std::string> get_required_extensions() const override;
    bool initialize(XrInstance instance, XrSession session, XrSpace base_space) override;
    bool update(XrTime time) override;
    bool is_initialized() const override { return initialized_; }
    std::string get_name() const override { return "HandTracker"; }
    void cleanup() override;
    
    // Get hand data
    const HandData& get_left_hand() const { return left_hand_; }
    const HandData& get_right_hand() const { return right_hand_; }
    
    // Get joint name for debugging
    static std::string get_joint_name(uint32_t joint_index);

private:
    bool initialize_hand(XrHandEXT hand_type, XrHandTrackerEXT& out_tracker);
    bool update_hand(XrHandTrackerEXT tracker, XrTime time, HandData& out_data);
    
    bool initialized_;
    XrInstance instance_;
    XrSession session_;
    XrSpace base_space_;
    
    // Hand trackers
    XrHandTrackerEXT left_hand_tracker_;
    XrHandTrackerEXT right_hand_tracker_;
    
    // Hand data
    HandData left_hand_;
    HandData right_hand_;
    
    // Extension function pointers
    PFN_xrCreateHandTrackerEXT pfn_create_hand_tracker_;
    PFN_xrDestroyHandTrackerEXT pfn_destroy_hand_tracker_;
    PFN_xrLocateHandJointsEXT pfn_locate_hand_joints_;
};

} // namespace oxr

