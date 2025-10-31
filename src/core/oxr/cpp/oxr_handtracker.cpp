#include "inc/oxr/oxr_handtracker.hpp"

#include <iostream>
#include <cstring>

namespace oxr {

HandTracker::HandTracker()
    : initialized_(false),
      instance_(XR_NULL_HANDLE),
      session_(XR_NULL_HANDLE),
      base_space_(XR_NULL_HANDLE),
      left_hand_tracker_(XR_NULL_HANDLE),
      right_hand_tracker_(XR_NULL_HANDLE),
      pfn_create_hand_tracker_(nullptr),
      pfn_destroy_hand_tracker_(nullptr),
      pfn_locate_hand_joints_(nullptr) {
}

HandTracker::~HandTracker() {
    cleanup();
}

void HandTracker::cleanup() {
    if (pfn_destroy_hand_tracker_) {
        if (left_hand_tracker_ != XR_NULL_HANDLE) {
            pfn_destroy_hand_tracker_(left_hand_tracker_);
            left_hand_tracker_ = XR_NULL_HANDLE;
        }
        if (right_hand_tracker_ != XR_NULL_HANDLE) {
            pfn_destroy_hand_tracker_(right_hand_tracker_);
            right_hand_tracker_ = XR_NULL_HANDLE;
        }
    }
    initialized_ = false;
}

std::vector<std::string> HandTracker::get_required_extensions() const {
    return {XR_EXT_HAND_TRACKING_EXTENSION_NAME};
}

bool HandTracker::initialize(XrInstance instance, XrSession session, XrSpace base_space) {
    instance_ = instance;
    session_ = session;
    base_space_ = base_space;
    
    // Check if system supports hand tracking
    XrSystemId system_id;
    XrSystemGetInfo system_info{XR_TYPE_SYSTEM_GET_INFO};
    system_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    
    XrResult result = xrGetSystem(instance_, &system_info, &system_id);
    if (XR_SUCCEEDED(result)) {
        XrSystemHandTrackingPropertiesEXT hand_tracking_props{XR_TYPE_SYSTEM_HAND_TRACKING_PROPERTIES_EXT};
        XrSystemProperties system_props{XR_TYPE_SYSTEM_PROPERTIES};
        system_props.next = &hand_tracking_props;
        
        result = xrGetSystemProperties(instance_, system_id, &system_props);
        if (XR_SUCCEEDED(result) && !hand_tracking_props.supportsHandTracking) {
            std::cerr << "Hand tracking not supported by this system" << std::endl;
            return false;
        }
    }
    
    // Get extension function pointers
    xrGetInstanceProcAddr(instance_, "xrCreateHandTrackerEXT",
        reinterpret_cast<PFN_xrVoidFunction*>(&pfn_create_hand_tracker_));
    xrGetInstanceProcAddr(instance_, "xrDestroyHandTrackerEXT",
        reinterpret_cast<PFN_xrVoidFunction*>(&pfn_destroy_hand_tracker_));
    xrGetInstanceProcAddr(instance_, "xrLocateHandJointsEXT",
        reinterpret_cast<PFN_xrVoidFunction*>(&pfn_locate_hand_joints_));
    
    if (!pfn_create_hand_tracker_ || !pfn_destroy_hand_tracker_ || !pfn_locate_hand_joints_) {
        std::cerr << "Failed to get hand tracking function pointers" << std::endl;
        return false;
    }
    
    // Create left and right hand trackers
    if (!initialize_hand(XR_HAND_LEFT_EXT, left_hand_tracker_)) {
        return false;
    }
    if (!initialize_hand(XR_HAND_RIGHT_EXT, right_hand_tracker_)) {
        return false;
    }
    
    initialized_ = true;
    std::cout << "HandTracker initialized (left + right)" << std::endl;
    return true;
}

bool HandTracker::initialize_hand(XrHandEXT hand_type, XrHandTrackerEXT& out_tracker) {
    XrHandTrackerCreateInfoEXT create_info{XR_TYPE_HAND_TRACKER_CREATE_INFO_EXT};
    create_info.hand = hand_type;
    create_info.handJointSet = XR_HAND_JOINT_SET_DEFAULT_EXT;
    
    XrResult result = pfn_create_hand_tracker_(session_, &create_info, &out_tracker);
    if (XR_FAILED(result)) {
        std::cerr << "Failed to create hand tracker: " << result << std::endl;
        return false;
    }
    
    return true;
}

bool HandTracker::update(XrTime time) {
    if (!initialized_) {
        return false;
    }
    
    update_hand(left_hand_tracker_, time, left_hand_);
    update_hand(right_hand_tracker_, time, right_hand_);
    
    return true;
}

bool HandTracker::update_hand(XrHandTrackerEXT tracker, XrTime time, HandData& out_data) {
    XrHandJointsLocateInfoEXT locate_info{XR_TYPE_HAND_JOINTS_LOCATE_INFO_EXT};
    locate_info.baseSpace = base_space_;
    locate_info.time = time;
    
    XrHandJointLocationEXT joint_locations[26];  // XR_HAND_JOINT_COUNT_EXT
    
    XrHandJointLocationsEXT locations{XR_TYPE_HAND_JOINT_LOCATIONS_EXT};
    locations.next = nullptr;
    locations.jointCount = 26;
    locations.jointLocations = joint_locations;
    
    XrResult result = pfn_locate_hand_joints_(tracker, &locate_info, &locations);
    if (XR_FAILED(result)) {
        out_data.is_active = false;
        return false;
    }
    
    out_data.is_active = locations.isActive;
    out_data.timestamp = time;
    
    for (uint32_t i = 0; i < 26; ++i) {
        const auto& joint_loc = joint_locations[i];
        auto& joint_data = out_data.joints[i];
        
        joint_data.position[0] = joint_loc.pose.position.x;
        joint_data.position[1] = joint_loc.pose.position.y;
        joint_data.position[2] = joint_loc.pose.position.z;
        
        joint_data.orientation[0] = joint_loc.pose.orientation.x;
        joint_data.orientation[1] = joint_loc.pose.orientation.y;
        joint_data.orientation[2] = joint_loc.pose.orientation.z;
        joint_data.orientation[3] = joint_loc.pose.orientation.w;
        
        joint_data.radius = joint_loc.radius;
        joint_data.is_valid = (joint_loc.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
                               (joint_loc.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);
    }
    
    return true;
}

std::string HandTracker::get_joint_name(uint32_t joint_index) {
    static const char* joint_names[] = {
        "Palm", "Wrist",
        "Thumb_Metacarpal", "Thumb_Proximal", "Thumb_Distal", "Thumb_Tip",
        "Index_Metacarpal", "Index_Proximal", "Index_Intermediate", "Index_Distal", "Index_Tip",
        "Middle_Metacarpal", "Middle_Proximal", "Middle_Intermediate", "Middle_Distal", "Middle_Tip",
        "Ring_Metacarpal", "Ring_Proximal", "Ring_Intermediate", "Ring_Distal", "Ring_Tip",
        "Little_Metacarpal", "Little_Proximal", "Little_Intermediate", "Little_Distal", "Little_Tip"
    };
    
    if (joint_index < 26) {
        return joint_names[joint_index];
    }
    return "Unknown";
}

} // namespace oxr

