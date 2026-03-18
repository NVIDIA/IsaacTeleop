// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_full_body_tracker_pico_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/full_body_bfbs_generated.h>

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// LiveFullBodyTrackerPicoImpl
// ============================================================================

std::unique_ptr<FullBodyMcapChannels> LiveFullBodyTrackerPicoImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                        std::string_view base_name)
{
    return std::make_unique<FullBodyMcapChannels>(writer, base_name, FullBodyPicoRecordingTraits::schema_name,
                                                  std::vector<std::string>(FullBodyPicoRecordingTraits::channels.begin(),
                                                                           FullBodyPicoRecordingTraits::channels.end()));
}

LiveFullBodyTrackerPicoImpl::LiveFullBodyTrackerPicoImpl(const OpenXRSessionHandles& handles,
                                                         std::unique_ptr<FullBodyMcapChannels> mcap_channels)
    : time_converter_(handles),
      base_space_(handles.space),
      body_tracker_(XR_NULL_HANDLE),
      pfn_create_body_tracker_(nullptr),
      pfn_destroy_body_tracker_(nullptr),
      pfn_locate_body_joints_(nullptr),
      mcap_channels_(std::move(mcap_channels))
{
    auto core_funcs = OpenXRCoreFunctions::load(handles.instance, handles.xrGetInstanceProcAddr);

    XrSystemId system_id;
    XrSystemGetInfo system_info{ XR_TYPE_SYSTEM_GET_INFO };
    system_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;

    XrResult result = core_funcs.xrGetSystem(handles.instance, &system_info, &system_id);
    if (XR_SUCCEEDED(result))
    {
        XrSystemBodyTrackingPropertiesBD body_tracking_props{ XR_TYPE_SYSTEM_BODY_TRACKING_PROPERTIES_BD };
        XrSystemProperties system_props{ XR_TYPE_SYSTEM_PROPERTIES };
        system_props.next = &body_tracking_props;

        result = core_funcs.xrGetSystemProperties(handles.instance, system_id, &system_props);
        if (XR_FAILED(result))
        {
            throw std::runtime_error("OpenXR: failed to get system properties: " + std::to_string(result));
        }
        if (!body_tracking_props.supportsBodyTracking)
        {
            std::cerr << "[FullBodyTrackerPico] Body tracking not supported by this system, running in limp mode"
                      << std::endl;
            return;
        }
    }
    else
    {
        throw std::runtime_error("OpenXR: failed to get system: " + std::to_string(result));
    }

    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrCreateBodyTrackerBD",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_create_body_tracker_));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrDestroyBodyTrackerBD",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_destroy_body_tracker_));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrLocateBodyJointsBD",
                          reinterpret_cast<PFN_xrVoidFunction*>(&pfn_locate_body_joints_));

    XrBodyTrackerCreateInfoBD create_info{ XR_TYPE_BODY_TRACKER_CREATE_INFO_BD };
    create_info.next = nullptr;
    create_info.jointSet = XR_BODY_JOINT_SET_FULL_BODY_JOINTS_BD;

    result = pfn_create_body_tracker_(handles.session, &create_info, &body_tracker_);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to create body tracker: " + std::to_string(result));
    }

    std::cout << "FullBodyTrackerPico initialized (24 joints)" << std::endl;
}

LiveFullBodyTrackerPicoImpl::~LiveFullBodyTrackerPicoImpl()
{
    if (body_tracker_ != XR_NULL_HANDLE)
    {
        assert(pfn_destroy_body_tracker_ != nullptr && "pfn_destroy_body_tracker must not be null");
        pfn_destroy_body_tracker_(body_tracker_);
        body_tracker_ = XR_NULL_HANDLE;
    }
}

bool LiveFullBodyTrackerPicoImpl::update(XrTime time)
{
    last_update_time_ = time;

    if (body_tracker_ == XR_NULL_HANDLE)
    {
        tracked_.data.reset();
        return true;
    }

    XrBodyJointsLocateInfoBD locate_info{ XR_TYPE_BODY_JOINTS_LOCATE_INFO_BD };
    locate_info.next = nullptr;
    locate_info.baseSpace = base_space_;
    locate_info.time = time;

    XrBodyJointLocationBD joint_locations[XR_BODY_JOINT_COUNT_BD];

    XrBodyJointLocationsBD locations{ XR_TYPE_BODY_JOINT_LOCATIONS_BD };
    locations.next = nullptr;
    locations.jointLocationCount = XR_BODY_JOINT_COUNT_BD;
    locations.jointLocations = joint_locations;

    XrResult result = pfn_locate_body_joints_(body_tracker_, &locate_info, &locations);
    if (XR_FAILED(result))
    {
        tracked_.data.reset();
        return false;
    }

    if (!tracked_.data)
    {
        tracked_.data = std::make_shared<FullBodyPosePicoT>();
    }

    tracked_.data->all_joint_poses_tracked = locations.allJointPosesTracked;

    if (!tracked_.data->joints)
    {
        tracked_.data->joints = std::make_shared<BodyJointsPico>();
    }

    for (uint32_t i = 0; i < XR_BODY_JOINT_COUNT_BD; ++i)
    {
        const auto& joint_loc = joint_locations[i];

        Point position(joint_loc.pose.position.x, joint_loc.pose.position.y, joint_loc.pose.position.z);
        Quaternion orientation(joint_loc.pose.orientation.x, joint_loc.pose.orientation.y, joint_loc.pose.orientation.z,
                               joint_loc.pose.orientation.w);
        Pose pose(position, orientation);

        bool is_valid = (joint_loc.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
                        (joint_loc.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);

        BodyJointPose joint_pose(pose, is_valid);
        tracked_.data->joints->mutable_joints()->Mutate(i, joint_pose);
    }

    if (mcap_channels_)
    {
        int64_t monotonic_ns = time_converter_.convert_xrtime_to_monotonic_ns(last_update_time_);
        DeviceDataTimestamp timestamp(monotonic_ns, monotonic_ns, last_update_time_);
        mcap_channels_->write(0, timestamp, tracked_.data);
    }

    return true;
}

const FullBodyPosePicoTrackedT& LiveFullBodyTrackerPicoImpl::get_body_pose() const
{
    return tracked_;
}

} // namespace core
