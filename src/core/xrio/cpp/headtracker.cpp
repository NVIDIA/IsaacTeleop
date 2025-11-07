#include "inc/xrio/headtracker.hpp"

#include <iostream>
#include <cstring>

namespace oxr {

// ============================================================================
// HeadTracker::Impl Implementation
// ============================================================================

// Factory function for creating the Impl
std::unique_ptr<HeadTracker::Impl> HeadTracker::Impl::create(XrInstance instance, XrSession session, XrSpace base_space) {
        // Create VIEW space for head tracking (represents HMD pose)
        XrReferenceSpaceCreateInfo create_info{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
        create_info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW;
        create_info.poseInReferenceSpace.orientation.w = 1.0f;
        
        XrSpace view_space = XR_NULL_HANDLE;
        XrResult result = xrCreateReferenceSpace(session, &create_info, &view_space);
        if (XR_FAILED(result)) {
            std::cerr << "Failed to create view space: " << result << std::endl;
            return nullptr;
        }
        
        std::cout << "HeadTracker initialized" << std::endl;
        
        // Create the Impl using private constructor
        // Use try-catch to ensure cleanup on construction failure
        try {
            return std::unique_ptr<Impl>(new Impl(base_space, view_space));
        } catch (...) {
            // Clean up view space if Impl construction fails
            if (view_space != XR_NULL_HANDLE) {
                xrDestroySpace(view_space);
            }
            throw;
        }
}

HeadTracker::Impl::~Impl() {
    cleanup();
}

// Override from ITrackerImpl
bool HeadTracker::Impl::update(XrTime time) {
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

const HeadPose& HeadTracker::Impl::get_head() const { return head_; }

// Private constructor
HeadTracker::Impl::Impl(XrSpace base_space, XrSpace view_space)
    : base_space_(base_space),
      view_space_(view_space) {
    
    head_.is_valid = false;
    head_.timestamp = 0;
}

void HeadTracker::Impl::cleanup() {
    if (view_space_ != XR_NULL_HANDLE) {
        xrDestroySpace(view_space_);
        view_space_ = XR_NULL_HANDLE;
    }
}

// ============================================================================
// HeadTracker Public Interface Implementation
// ============================================================================

HeadTracker::HeadTracker() {
}

HeadTracker::~HeadTracker() {
    // Session owns the impl, weak_ptr will detect if it's destroyed
}

std::vector<std::string> HeadTracker::get_required_extensions() const {
    // Head tracking doesn't require special extensions - it's part of core OpenXR
    return {};
}

const HeadPose& HeadTracker::get_head() const {
    static const HeadPose empty_pose{};
    auto impl = cached_impl_.lock();
    if (!impl) return empty_pose;
    return impl->get_head();
}

std::shared_ptr<ITrackerImpl> HeadTracker::initialize(XrInstance instance, XrSession session, XrSpace base_space) {
    auto impl = Impl::create(instance, session, base_space);
    if (impl) {
        // We need to convert unique_ptr to shared_ptr to use weak_ptr
        // The session will own it, so we create a shared_ptr and cache a weak_ptr
        auto shared = std::shared_ptr<Impl>(impl.release());
        cached_impl_ = shared;
        return shared;
    }
    return nullptr;
}

bool HeadTracker::is_initialized() const {
    return !cached_impl_.expired();
}

} // namespace oxr

