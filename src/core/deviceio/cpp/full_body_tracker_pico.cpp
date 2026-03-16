// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/full_body_tracker_pico.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/full_body_bfbs_generated.h>

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// FullBodyTrackerPico::Impl
// ============================================================================

class FullBodyTrackerPico::Impl : public ITrackerImpl
{
public:
    explicit Impl(const OpenXRSessionHandles& handles);
    ~Impl();

    bool update(XrTime time) override;
    void serialize_all(size_t channel_index, const RecordCallback& callback) const override;

    const FullBodyPosePicoTrackedT& get_body_pose() const;

private:
    XrTimeConverter time_converter_;
    XrSpace base_space_;
    XrBodyTrackerBD body_tracker_;
    FullBodyPosePicoTrackedT tracked_;
    XrTime last_update_time_ = 0;

    PFN_xrCreateBodyTrackerBD pfn_create_body_tracker_;
    PFN_xrDestroyBodyTrackerBD pfn_destroy_body_tracker_;
    PFN_xrLocateBodyJointsBD pfn_locate_body_joints_;
};

FullBodyTrackerPico::Impl::Impl(const OpenXRSessionHandles& handles)
    : time_converter_(handles),
      base_space_(handles.space),
      body_tracker_(XR_NULL_HANDLE),
      pfn_create_body_tracker_(nullptr),
      pfn_destroy_body_tracker_(nullptr),
      pfn_locate_body_joints_(nullptr)
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

FullBodyTrackerPico::Impl::~Impl()
{
    assert(pfn_destroy_body_tracker_ != nullptr && "pfn_destroy_body_tracker must not be null");

    if (body_tracker_ != XR_NULL_HANDLE)
    {
        pfn_destroy_body_tracker_(body_tracker_);
        body_tracker_ = XR_NULL_HANDLE;
    }
}

bool FullBodyTrackerPico::Impl::update(XrTime time)
{
    last_update_time_ = time;

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

    return true;
}

const FullBodyPosePicoTrackedT& FullBodyTrackerPico::Impl::get_body_pose() const
{
    return tracked_;
}

void FullBodyTrackerPico::Impl::serialize_all(size_t channel_index, const RecordCallback& callback) const
{
    if (channel_index != 0)
    {
        throw std::runtime_error("FullBodyTrackerPico::serialize_all: invalid channel_index " +
                                 std::to_string(channel_index) + " (only channel 0 exists)");
    }

    flatbuffers::FlatBufferBuilder builder(256);

    int64_t monotonic_ns = time_converter_.convert_xrtime_to_monotonic_ns(last_update_time_);
    DeviceDataTimestamp timestamp(monotonic_ns, monotonic_ns, last_update_time_);

    FullBodyPosePicoRecordBuilder record_builder(builder);
    if (tracked_.data)
    {
        auto data_offset = FullBodyPosePico::Pack(builder, tracked_.data.get());
        record_builder.add_data(data_offset);
    }
    record_builder.add_timestamp(&timestamp);
    builder.Finish(record_builder.Finish());

    callback(monotonic_ns, builder.GetBufferPointer(), builder.GetSize());
}

// ============================================================================
// FullBodyTrackerPico Public Interface
// ============================================================================

std::vector<std::string> FullBodyTrackerPico::get_required_extensions() const
{
    return { XR_BD_BODY_TRACKING_EXTENSION_NAME };
}

std::string_view FullBodyTrackerPico::get_schema_text() const
{
    return std::string_view(reinterpret_cast<const char*>(FullBodyPosePicoRecordBinarySchema::data()),
                            FullBodyPosePicoRecordBinarySchema::size());
}

const FullBodyPosePicoTrackedT& FullBodyTrackerPico::get_body_pose(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_body_pose();
}

std::shared_ptr<ITrackerImpl> FullBodyTrackerPico::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles);
}

} // namespace core
