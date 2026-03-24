// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_hand_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/hand_bfbs_generated.h>

#include <cassert>
#include <cstring>
#include <iostream>
#include <stdexcept>

namespace core
{

// ============================================================================
// LiveHandTrackerImpl
// ============================================================================

std::unique_ptr<HandMcapChannels> LiveHandTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                            std::string_view base_name)
{
    return std::make_unique<HandMcapChannels>(
        writer, base_name, HandRecordingTraits::schema_name,
        std::vector<std::string>(HandRecordingTraits::channels.begin(), HandRecordingTraits::channels.end()));
}

LiveHandTrackerImpl::LiveHandTrackerImpl(const OpenXRSessionHandles& handles,
                                         std::unique_ptr<HandMcapChannels> mcap_channels)
    : time_converter_(handles),
      base_space_(handles.space),
      left_hand_tracker_(XR_NULL_HANDLE),
      right_hand_tracker_(XR_NULL_HANDLE),
      pfn_create_hand_tracker_(nullptr),
      pfn_destroy_hand_tracker_(nullptr),
      pfn_locate_hand_joints_(nullptr),
      mcap_channels_(std::move(mcap_channels))
{
    auto core_funcs = OpenXRCoreFunctions::load(handles.instance, handles.xrGetInstanceProcAddr);

    XrSystemId system_id;
    XrSystemGetInfo system_info{ XR_TYPE_SYSTEM_GET_INFO };
    system_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;

    XrResult result = core_funcs.xrGetSystem(handles.instance, &system_info, &system_id);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to get OpenXR system: " + std::to_string(result));
    }

    XrSystemHandTrackingPropertiesEXT hand_tracking_props{ XR_TYPE_SYSTEM_HAND_TRACKING_PROPERTIES_EXT };
    XrSystemProperties system_props{ XR_TYPE_SYSTEM_PROPERTIES };
    system_props.next = &hand_tracking_props;

    result = core_funcs.xrGetSystemProperties(handles.instance, system_id, &system_props);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to get system properties: " + std::to_string(result));
    }
    if (!hand_tracking_props.supportsHandTracking)
    {
        throw std::runtime_error("Hand tracking not supported by this system");
    }

    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrCreateHandTrackerEXT",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_create_hand_tracker_));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrDestroyHandTrackerEXT",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_destroy_hand_tracker_));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrLocateHandJointsEXT",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_locate_hand_joints_));

    if (!pfn_create_hand_tracker_ || !pfn_destroy_hand_tracker_ || !pfn_locate_hand_joints_)
    {
        throw std::runtime_error("Failed to get hand tracking function pointers");
    }

    XrHandTrackerCreateInfoEXT create_info{ XR_TYPE_HAND_TRACKER_CREATE_INFO_EXT };
    create_info.handJointSet = XR_HAND_JOINT_SET_DEFAULT_EXT;

    create_info.hand = XR_HAND_LEFT_EXT;
    result = pfn_create_hand_tracker_(handles.session, &create_info, &left_hand_tracker_);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to create left hand tracker: " + std::to_string(result));
    }

    create_info.hand = XR_HAND_RIGHT_EXT;
    result = pfn_create_hand_tracker_(handles.session, &create_info, &right_hand_tracker_);
    if (XR_FAILED(result))
    {
        if (left_hand_tracker_ != XR_NULL_HANDLE)
        {
            pfn_destroy_hand_tracker_(left_hand_tracker_);
        }
        throw std::runtime_error("Failed to create right hand tracker: " + std::to_string(result));
    }

    std::cout << "HandTracker initialized (left + right)" << std::endl;
}

LiveHandTrackerImpl::~LiveHandTrackerImpl()
{
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

void LiveHandTrackerImpl::update(XrTime time)
{
    last_update_time_ = time;
    update_hand(left_hand_tracker_, time, left_tracked_);
    update_hand(right_hand_tracker_, time, right_tracked_);

    if (mcap_channels_)
    {
        int64_t monotonic_ns = time_converter_.convert_xrtime_to_monotonic_ns(last_update_time_);
        DeviceDataTimestamp timestamp(monotonic_ns, monotonic_ns, last_update_time_);
        mcap_channels_->write(0, timestamp, left_tracked_.data);
        mcap_channels_->write(1, timestamp, right_tracked_.data);
    }
}

const HandPoseTrackedT& LiveHandTrackerImpl::get_left_hand() const
{
    return left_tracked_;
}

const HandPoseTrackedT& LiveHandTrackerImpl::get_right_hand() const
{
    return right_tracked_;
}

void LiveHandTrackerImpl::update_hand(XrHandTrackerEXT tracker, XrTime time, HandPoseTrackedT& tracked)
{
    XrHandJointsLocateInfoEXT locate_info{ XR_TYPE_HAND_JOINTS_LOCATE_INFO_EXT };
    locate_info.baseSpace = base_space_;
    locate_info.time = time;

    XrHandJointLocationEXT joint_locations[XR_HAND_JOINT_COUNT_EXT];

    XrHandJointLocationsEXT locations{ XR_TYPE_HAND_JOINT_LOCATIONS_EXT };
    locations.next = nullptr;
    locations.jointCount = XR_HAND_JOINT_COUNT_EXT;
    locations.jointLocations = joint_locations;

    XrResult result = pfn_locate_hand_joints_(tracker, &locate_info, &locations);
    if (XR_FAILED(result))
    {
        tracked.data.reset();
        throw std::runtime_error("[HandTracker] xrLocateHandJointsEXT failed: " + std::to_string(result));
    }

    if (!locations.isActive)
    {
        // Policy: inactive hand is a common runtime condition; non-fatal.
        tracked.data.reset();
        return;
    }

    if (!tracked.data)
    {
        tracked.data = std::make_shared<HandPoseT>();
    }

    if (!tracked.data->joints)
    {
        tracked.data->joints = std::make_shared<HandJoints>();
    }

    for (uint32_t i = 0; i < XR_HAND_JOINT_COUNT_EXT; ++i)
    {
        const auto& joint_loc = joint_locations[i];

        Point position(joint_loc.pose.position.x, joint_loc.pose.position.y, joint_loc.pose.position.z);
        Quaternion orientation(joint_loc.pose.orientation.x, joint_loc.pose.orientation.y, joint_loc.pose.orientation.z,
                               joint_loc.pose.orientation.w);
        Pose pose(position, orientation);

        bool is_valid = (joint_loc.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
                        (joint_loc.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);

        HandJointPose joint_pose(pose, is_valid, joint_loc.radius);
        tracked.data->joints->mutable_poses()->Mutate(i, joint_pose);
    }
}

} // namespace core
