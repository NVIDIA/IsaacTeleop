// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/head_tracker.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <cstring>
#include <iostream>

namespace core
{


// ============================================================================
// HeadTracker::Impl Implementation
// ============================================================================

// Constructor - throws std::runtime_error on failure
HeadTracker::Impl::Impl(const OpenXRSessionHandles& handles)
    : core_funcs_(OpenXRCoreFunctions::load(handles.instance, handles.xrGetInstanceProcAddr)),
      base_space_(handles.space),
      view_space_(createReferenceSpace(core_funcs_,
                                       handles.session,
                                       { .type = XR_TYPE_REFERENCE_SPACE_CREATE_INFO,
                                         .referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW,
                                         .poseInReferenceSpace = { .orientation = { 0, 0, 0, 1 } } })),
      head_{}
{
}

// Override from ITrackerImpl
bool HeadTracker::Impl::update(XrTime time)
{
    // Locate the view space (head) relative to the base space
    XrSpaceLocation location{ XR_TYPE_SPACE_LOCATION };
    XrResult result = core_funcs_.xrLocateSpace(view_space_.get(), base_space_, time, &location);

    if (XR_FAILED(result))
    {
        head_.mutate_is_valid(false);
        return false;
    }

    // Check if tracking is valid
    bool position_valid = (location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) != 0;
    bool orientation_valid = (location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT) != 0;

    head_.mutate_is_valid(position_valid && orientation_valid);

    // Update timestamp (device time and common time)
    head_.mutable_timestamp() = Timestamp(time, time);

    if (head_.is_valid())
    {
        // Create pose from position and orientation using FlatBuffers structs
        Point position(location.pose.position.x, location.pose.position.y, location.pose.position.z);
        Quaternion orientation(location.pose.orientation.x, location.pose.orientation.y, location.pose.orientation.z,
                               location.pose.orientation.w);
        head_.mutable_pose() = Pose(position, orientation);
    }
    else
    {
        // Invalid - reset pose to default
        head_.mutable_pose() = Pose();
    }

    return true;
}

const HeadPose& HeadTracker::Impl::get_head() const
{
    return head_;
}

Timestamp HeadTracker::Impl::serialize(flatbuffers::FlatBufferBuilder& builder, size_t /*channel_index*/) const
{
    HeadPoseRecordBuilder record_builder(builder);
    record_builder.add_data(&head_);
    builder.Finish(record_builder.Finish());

    return head_.timestamp();
}

// ============================================================================
// HeadTracker Public Interface Implementation
// ============================================================================

std::vector<std::string> HeadTracker::get_required_extensions() const
{
    // Head tracking doesn't require special extensions - it's part of core OpenXR
    return {};
}

const HeadPose& HeadTracker::get_head(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_head();
}

std::shared_ptr<ITrackerImpl> HeadTracker::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles);
}

} // namespace core
