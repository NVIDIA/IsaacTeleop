// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_head_tracker_impl.hpp"

#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// LiveHeadTrackerImpl
// ============================================================================

LiveHeadTrackerImpl::LiveHeadTrackerImpl(const OpenXRSessionHandles& handles)
    : core_funcs_(OpenXRCoreFunctions::load(handles.instance, handles.xrGetInstanceProcAddr)),
      time_converter_(handles),
      base_space_(handles.space),
      view_space_(createReferenceSpace(core_funcs_,
                                       handles.session,
                                       { .type = XR_TYPE_REFERENCE_SPACE_CREATE_INFO,
                                         .referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW,
                                         .poseInReferenceSpace = { .orientation = { 0, 0, 0, 1 } } })),
      tracked_{}
{
}

bool LiveHeadTrackerImpl::update(XrTime time)
{
    last_update_time_ = time;

    XrSpaceLocation location{ XR_TYPE_SPACE_LOCATION };
    XrResult result = core_funcs_.xrLocateSpace(view_space_.get(), base_space_, time, &location);

    if (XR_FAILED(result))
    {
        tracked_.data.reset();
        return false;
    }

    bool position_valid = (location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) != 0;
    bool orientation_valid = (location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT) != 0;

    if (!tracked_.data)
    {
        tracked_.data = std::make_shared<HeadPoseT>();
    }

    tracked_.data->is_valid = position_valid && orientation_valid;

    if (tracked_.data->is_valid)
    {
        Point position(location.pose.position.x, location.pose.position.y, location.pose.position.z);
        Quaternion orientation(location.pose.orientation.x, location.pose.orientation.y, location.pose.orientation.z,
                               location.pose.orientation.w);
        tracked_.data->pose = std::make_shared<Pose>(position, orientation);
    }
    else
    {
        tracked_.data->pose.reset();
    }

    return true;
}

const HeadPoseTrackedT& LiveHeadTrackerImpl::get_head() const
{
    return tracked_;
}

void LiveHeadTrackerImpl::serialize_all(size_t channel_index, const RecordCallback& callback) const
{
    if (channel_index != 0)
    {
        throw std::runtime_error("LiveHeadTrackerImpl::serialize_all: invalid channel_index " +
                                 std::to_string(channel_index) + " (only channel 0 exists)");
    }

    flatbuffers::FlatBufferBuilder builder(256);

    int64_t monotonic_ns = time_converter_.convert_xrtime_to_monotonic_ns(last_update_time_);
    DeviceDataTimestamp timestamp(monotonic_ns, monotonic_ns, last_update_time_);

    HeadPoseRecordBuilder record_builder(builder);
    if (tracked_.data)
    {
        auto data_offset = HeadPose::Pack(builder, tracked_.data.get());
        record_builder.add_data(data_offset);
    }
    record_builder.add_timestamp(&timestamp);
    builder.Finish(record_builder.Finish());

    callback(monotonic_ns, builder.GetBufferPointer(), builder.GetSize());
}

} // namespace core
