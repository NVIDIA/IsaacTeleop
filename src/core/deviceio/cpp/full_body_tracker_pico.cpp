// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/full_body_tracker_pico.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// FullBodyTrackerPicoImpl Implementation (namespace-level, not nested)
// ============================================================================

class FullBodyTrackerPicoImpl : public ITrackerImpl
{
public:
    // Constructor - throws std::runtime_error on failure
    explicit FullBodyTrackerPicoImpl(const OpenXRSessionHandles& handles);
    ~FullBodyTrackerPicoImpl();

    // Override from ITrackerImpl
    bool update(XrTime time) override;
    Timestamp serialize(flatbuffers::FlatBufferBuilder& builder, size_t channel_index) const override;

    // Get body pose data
    const FullBodyPosePicoT& get_body_pose() const;

private:
    XrSpace base_space_;
    XrBodyTrackerBD body_tracker_;
    FullBodyPosePicoT body_pose_;

    // Extension function pointers
    PFN_xrCreateBodyTrackerBD pfn_create_body_tracker_;
    PFN_xrDestroyBodyTrackerBD pfn_destroy_body_tracker_;
    PFN_xrLocateBodyJointsBD pfn_locate_body_joints_;
};

FullBodyTrackerPicoImpl::FullBodyTrackerPicoImpl(const OpenXRSessionHandles& handles)
    : base_space_(handles.space),
      body_tracker_(XR_NULL_HANDLE),
      pfn_create_body_tracker_(nullptr),
      pfn_destroy_body_tracker_(nullptr),
      pfn_locate_body_joints_(nullptr)
{
    // Load core OpenXR functions dynamically using the provided xrGetInstanceProcAddr
    auto core_funcs = OpenXRCoreFunctions::load(handles.instance, handles.xrGetInstanceProcAddr);

    // Check if system supports body tracking
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
            throw std::runtime_error("Body tracking not supported by this system");
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

    if (!pfn_create_body_tracker_ || !pfn_destroy_body_tracker_ || !pfn_locate_body_joints_)
    {
        throw std::runtime_error("Failed to get body tracking function pointers");
    }

    // Create body tracker for full body joints (24 joints)
    XrBodyTrackerCreateInfoBD create_info{ XR_TYPE_BODY_TRACKER_CREATE_INFO_BD };
    create_info.next = nullptr;
    create_info.jointSet = XR_BODY_JOINT_SET_FULL_BODY_JOINTS_BD;

    result = pfn_create_body_tracker_(handles.session, &create_info, &body_tracker_);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to create body tracker: " + std::to_string(result));
    }

    body_pose_.is_active = false;

    std::cout << "FullBodyTrackerPico initialized (24 joints)" << std::endl;
}

FullBodyTrackerPicoImpl::~FullBodyTrackerPicoImpl()
{
    // pfn_destroy_body_tracker_ should never be null (verified in constructor)
    assert(pfn_destroy_body_tracker_ != nullptr && "pfn_destroy_body_tracker must not be null");

    if (body_tracker_ != XR_NULL_HANDLE)
    {
        pfn_destroy_body_tracker_(body_tracker_);
        body_tracker_ = XR_NULL_HANDLE;
    }
}

bool FullBodyTrackerPicoImpl::update(XrTime time)
{
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
        body_pose_.is_active = false;
        return false;
    }

    // allJointPosesTracked indicates if all joint poses are valid
    body_pose_.is_active = locations.allJointPosesTracked;

    // Update timestamp (device time and common time)
    body_pose_.timestamp = std::make_shared<Timestamp>(time, time);

    // Ensure joints struct is allocated
    if (!body_pose_.joints)
    {
        body_pose_.joints = std::make_unique<BodyJointsPico>();
    }

    for (uint32_t i = 0; i < XR_BODY_JOINT_COUNT_BD; ++i)
    {
        const auto& joint_loc = joint_locations[i];

        // Create Pose from position and orientation using FlatBuffers structs
        Point position(joint_loc.pose.position.x, joint_loc.pose.position.y, joint_loc.pose.position.z);
        Quaternion orientation(joint_loc.pose.orientation.x, joint_loc.pose.orientation.y, joint_loc.pose.orientation.z,
                               joint_loc.pose.orientation.w);
        Pose pose(position, orientation);

        bool is_valid = (joint_loc.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
                        (joint_loc.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);

        // Create BodyJointPose and set it in the array
        BodyJointPose joint_pose(pose, is_valid);
        body_pose_.joints->mutable_joints()->Mutate(i, joint_pose);
    }

    return true;
}

const FullBodyPosePicoT& FullBodyTrackerPicoImpl::get_body_pose() const
{
    return body_pose_;
}

Timestamp FullBodyTrackerPicoImpl::serialize(flatbuffers::FlatBufferBuilder& builder, size_t /*channel_index*/) const
{
    auto offset = FullBodyPosePico::Pack(builder, &body_pose_);
    builder.Finish(offset);

    if (body_pose_.timestamp)
    {
        return *body_pose_.timestamp;
    }
    return Timestamp{};
}

// ============================================================================
// FullBodyTrackerPico Public Interface Implementation
// ============================================================================

std::vector<std::string> FullBodyTrackerPico::get_required_extensions() const
{
    return { XR_BD_BODY_TRACKING_EXTENSION_NAME };
}

const FullBodyPosePicoT& FullBodyTrackerPico::get_body_pose(const DeviceIOSession& session) const
{
    return static_cast<const FullBodyTrackerPicoImpl&>(session.get_tracker_impl(*this)).get_body_pose();
}

std::shared_ptr<ITrackerImpl> FullBodyTrackerPico::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<FullBodyTrackerPicoImpl>(handles);
}

} // namespace core
