// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/xrio/handtracker.hpp"

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{


// ============================================================================
// HandTracker::Impl Implementation
// ============================================================================

// Factory function for creating the Impl
std::unique_ptr<HandTracker::Impl> HandTracker::Impl::create(const OpenXRSessionHandles& handles)
{
    // Load core OpenXR functions dynamically using the provided xrGetInstanceProcAddr
    OpenXRCoreFunctions core_funcs;
    if (!core_funcs.load(handles.instance, handles.xrGetInstanceProcAddr))
    {
        std::cerr << "Failed to load core OpenXR functions for HandTracker" << std::endl;
        return nullptr;
    }

    // Check if system supports hand tracking
    XrSystemId system_id;
    XrSystemGetInfo system_info{ XR_TYPE_SYSTEM_GET_INFO };
    system_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;

    XrResult result = core_funcs.xrGetSystem(handles.instance, &system_info, &system_id);
    if (XR_SUCCEEDED(result))
    {
        XrSystemHandTrackingPropertiesEXT hand_tracking_props{ XR_TYPE_SYSTEM_HAND_TRACKING_PROPERTIES_EXT };
        XrSystemProperties system_props{ XR_TYPE_SYSTEM_PROPERTIES };
        system_props.next = &hand_tracking_props;

        result = core_funcs.xrGetSystemProperties(handles.instance, system_id, &system_props);
        if (XR_SUCCEEDED(result) && !hand_tracking_props.supportsHandTracking)
        {
            std::cerr << "Hand tracking not supported by this system" << std::endl;
            return nullptr;
        }
    }

    // Get extension function pointers using the provided xrGetInstanceProcAddr
    PFN_xrCreateHandTrackerEXT pfn_create_hand_tracker = nullptr;
    PFN_xrDestroyHandTrackerEXT pfn_destroy_hand_tracker = nullptr;
    PFN_xrLocateHandJointsEXT pfn_locate_hand_joints = nullptr;

    handles.xrGetInstanceProcAddr(
        handles.instance, "xrCreateHandTrackerEXT", reinterpret_cast<PFN_xrVoidFunction*>(&pfn_create_hand_tracker));
    handles.xrGetInstanceProcAddr(
        handles.instance, "xrDestroyHandTrackerEXT", reinterpret_cast<PFN_xrVoidFunction*>(&pfn_destroy_hand_tracker));
    handles.xrGetInstanceProcAddr(
        handles.instance, "xrLocateHandJointsEXT", reinterpret_cast<PFN_xrVoidFunction*>(&pfn_locate_hand_joints));

    if (!pfn_create_hand_tracker || !pfn_destroy_hand_tracker || !pfn_locate_hand_joints)
    {
        std::cerr << "Failed to get hand tracking function pointers" << std::endl;
        return nullptr;
    }

    // Create hand trackers
    XrHandTrackerEXT left_hand_tracker = XR_NULL_HANDLE;
    XrHandTrackerEXT right_hand_tracker = XR_NULL_HANDLE;

    if (!create_hand_tracker(handles.session, XR_HAND_LEFT_EXT, pfn_create_hand_tracker, left_hand_tracker))
    {
        return nullptr;
    }

    if (!create_hand_tracker(handles.session, XR_HAND_RIGHT_EXT, pfn_create_hand_tracker, right_hand_tracker))
    {
        // Clean up left hand tracker on failure
        if (left_hand_tracker != XR_NULL_HANDLE)
        {
            pfn_destroy_hand_tracker(left_hand_tracker);
        }
        return nullptr;
    }

    std::cout << "HandTracker initialized (left + right)" << std::endl;

    // Create the Impl using private constructor
    // Use try-catch to ensure cleanup on construction failure
    try
    {
        return std::unique_ptr<Impl>(new Impl(handles.space, left_hand_tracker, right_hand_tracker,
                                              pfn_create_hand_tracker, pfn_destroy_hand_tracker, pfn_locate_hand_joints));
    }
    catch (...)
    {
        // Clean up hand trackers if Impl construction fails
        if (left_hand_tracker != XR_NULL_HANDLE)
        {
            pfn_destroy_hand_tracker(left_hand_tracker);
        }
        if (right_hand_tracker != XR_NULL_HANDLE)
        {
            pfn_destroy_hand_tracker(right_hand_tracker);
        }
        throw;
    }
}

HandTracker::Impl::~Impl()
{
    cleanup();
}

// Override from ITrackerImpl
bool HandTracker::Impl::update(XrTime time)
{
    bool left_ok = update_hand(left_hand_tracker_, time, left_hand_);
    bool right_ok = update_hand(right_hand_tracker_, time, right_hand_);

    // Return true if at least one hand updated successfully
    return left_ok || right_ok;
}

const HandData& HandTracker::Impl::get_left_hand() const
{
    return left_hand_;
}
const HandData& HandTracker::Impl::get_right_hand() const
{
    return right_hand_;
}

// Private constructor
HandTracker::Impl::Impl(XrSpace base_space,
                        XrHandTrackerEXT left_hand_tracker,
                        XrHandTrackerEXT right_hand_tracker,
                        PFN_xrCreateHandTrackerEXT pfn_create,
                        PFN_xrDestroyHandTrackerEXT pfn_destroy,
                        PFN_xrLocateHandJointsEXT pfn_locate)
    : base_space_(base_space),
      left_hand_tracker_(left_hand_tracker),
      right_hand_tracker_(right_hand_tracker),
      pfn_create_hand_tracker_(pfn_create),
      pfn_destroy_hand_tracker_(pfn_destroy),
      pfn_locate_hand_joints_(pfn_locate)
{

    // Ensure critical function pointers are not null
    assert(pfn_destroy != nullptr && "pfn_destroy_hand_tracker must not be null");
    assert(pfn_locate != nullptr && "pfn_locate_hand_joints must not be null");

    left_hand_.is_active = false;
    right_hand_.is_active = false;
}

// Helper function for creating a single hand tracker
bool HandTracker::Impl::create_hand_tracker(XrSession session,
                                            XrHandEXT hand_type,
                                            PFN_xrCreateHandTrackerEXT pfn_create,
                                            XrHandTrackerEXT& out_tracker)
{
    XrHandTrackerCreateInfoEXT create_info{ XR_TYPE_HAND_TRACKER_CREATE_INFO_EXT };
    create_info.hand = hand_type;
    create_info.handJointSet = XR_HAND_JOINT_SET_DEFAULT_EXT;

    XrResult result = pfn_create(session, &create_info, &out_tracker);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to create hand tracker: " << result << std::endl;
        return false;
    }

    return true;
}

void HandTracker::Impl::cleanup()
{
    // pfn_destroy_hand_tracker_ should never be null (verified in constructor)
    assert(pfn_destroy_hand_tracker_ != nullptr && "pfn_destroy_hand_tracker must not be null");

    if (left_hand_tracker_ != XR_NULL_HANDLE)
    {
        pfn_destroy_hand_tracker_(left_hand_tracker_);
        left_hand_tracker_ = XR_NULL_HANDLE;
    }
    if (right_hand_tracker_ != XR_NULL_HANDLE)
    {
        pfn_destroy_hand_tracker_(right_hand_tracker_);
        right_hand_tracker_ = XR_NULL_HANDLE;
    }
}

bool HandTracker::Impl::update_hand(XrHandTrackerEXT tracker, XrTime time, HandData& out_data)
{
    XrHandJointsLocateInfoEXT locate_info{ XR_TYPE_HAND_JOINTS_LOCATE_INFO_EXT };
    locate_info.baseSpace = base_space_;
    locate_info.time = time;

    XrHandJointLocationEXT joint_locations[26]; // XR_HAND_JOINT_COUNT_EXT

    XrHandJointLocationsEXT locations{ XR_TYPE_HAND_JOINT_LOCATIONS_EXT };
    locations.next = nullptr;
    locations.jointCount = 26;
    locations.jointLocations = joint_locations;

    XrResult result = pfn_locate_hand_joints_(tracker, &locate_info, &locations);
    if (XR_FAILED(result))
    {
        out_data.is_active = false;
        return false;
    }

    out_data.is_active = locations.isActive;
    out_data.timestamp = time;

    for (uint32_t i = 0; i < 26; ++i)
    {
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

// ============================================================================
// HandTracker Public Interface Implementation
// ============================================================================

HandTracker::HandTracker()
{
}

HandTracker::~HandTracker()
{
    // Session owns the impl, weak_ptr will detect if it's destroyed
}

std::vector<std::string> HandTracker::get_required_extensions() const
{
    return { XR_EXT_HAND_TRACKING_EXTENSION_NAME };
}

const HandData& HandTracker::get_left_hand() const
{
    static const HandData empty_data{};
    auto impl = cached_impl_.lock();
    if (!impl)
        return empty_data;
    return impl->get_left_hand();
}

const HandData& HandTracker::get_right_hand() const
{
    static const HandData empty_data{};
    auto impl = cached_impl_.lock();
    if (!impl)
        return empty_data;
    return impl->get_right_hand();
}

std::shared_ptr<ITrackerImpl> HandTracker::initialize(const OpenXRSessionHandles& handles)
{
    auto impl = Impl::create(handles);
    if (impl)
    {
        // We need to convert unique_ptr to shared_ptr to use weak_ptr
        // The session will own it, so we create a shared_ptr and cache a weak_ptr
        auto shared = std::shared_ptr<Impl>(impl.release());
        cached_impl_ = shared;
        return shared;
    }
    return nullptr;
}

bool HandTracker::is_initialized() const
{
    return !cached_impl_.expired();
}

std::string HandTracker::get_joint_name(uint32_t joint_index)
{
    static const char* joint_names[] = { "Palm",
                                         "Wrist",
                                         "Thumb_Metacarpal",
                                         "Thumb_Proximal",
                                         "Thumb_Distal",
                                         "Thumb_Tip",
                                         "Index_Metacarpal",
                                         "Index_Proximal",
                                         "Index_Intermediate",
                                         "Index_Distal",
                                         "Index_Tip",
                                         "Middle_Metacarpal",
                                         "Middle_Proximal",
                                         "Middle_Intermediate",
                                         "Middle_Distal",
                                         "Middle_Tip",
                                         "Ring_Metacarpal",
                                         "Ring_Proximal",
                                         "Ring_Intermediate",
                                         "Ring_Distal",
                                         "Ring_Tip",
                                         "Little_Metacarpal",
                                         "Little_Proximal",
                                         "Little_Intermediate",
                                         "Little_Distal",
                                         "Little_Tip" };

    if (joint_index < 26)
    {
        return joint_names[joint_index];
    }
    return "Unknown";
}

} // namespace core
