#include "inc/oxr/oxr_headtracker.hpp"

#include <iostream>
#include <cstring>

namespace oxr {

HeadTracker::HeadTracker()
    : initialized_(false),
      session_(XR_NULL_HANDLE),
      base_space_(XR_NULL_HANDLE),
      view_space_(XR_NULL_HANDLE) {
}

HeadTracker::~HeadTracker() {
    cleanup();
}

void HeadTracker::cleanup() {
    if (view_space_ != XR_NULL_HANDLE) {
        xrDestroySpace(view_space_);
        view_space_ = XR_NULL_HANDLE;
    }
    initialized_ = false;
}

std::vector<std::string> HeadTracker::get_required_extensions() const {
    // Head tracking doesn't require special extensions - it's part of core OpenXR
    return {};
}

bool HeadTracker::initialize(XrInstance instance, XrSession session, XrSpace base_space) {
    session_ = session;
    base_space_ = base_space;
    
    // Create VIEW space for head tracking (represents HMD pose)
    XrReferenceSpaceCreateInfo create_info{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
    create_info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW;
    create_info.poseInReferenceSpace.orientation.w = 1.0f;
    
    XrResult result = xrCreateReferenceSpace(session, &create_info, &view_space_);
    if (XR_FAILED(result)) {
        std::cerr << "Failed to create view space: " << result << std::endl;
        return false;
    }
    
    initialized_ = true;
    std::cout << "HeadTracker initialized" << std::endl;
    return true;
}

bool HeadTracker::update(XrTime time) {
    if (!initialized_) {
        return false;
    }
    
    // Locate the view space (head) relative to the base space
    XrSpaceLocation location{XR_TYPE_SPACE_LOCATION};
    XrResult result = xrLocateSpace(view_space_, base_space_, time, &location);
    
    if (XR_FAILED(result)) {
        head_.is_valid = false;
        return false;
    }
    
    // Check if tracking is valid
    bool position_valid = (location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) != 0;
    bool orientation_valid = (location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT) != 0;
    
    head_.is_valid = position_valid && orientation_valid;
    head_.timestamp = time;
    
    if (head_.is_valid) {
        // Copy position
        head_.position[0] = location.pose.position.x;
        head_.position[1] = location.pose.position.y;
        head_.position[2] = location.pose.position.z;
        
        // Copy orientation
        head_.orientation[0] = location.pose.orientation.x;
        head_.orientation[1] = location.pose.orientation.y;
        head_.orientation[2] = location.pose.orientation.z;
        head_.orientation[3] = location.pose.orientation.w;
    } else {
        // Invalid - zero out
        memset(head_.position, 0, sizeof(head_.position));
        memset(head_.orientation, 0, sizeof(head_.orientation));
    }
    
    return true;
}

} // namespace oxr

