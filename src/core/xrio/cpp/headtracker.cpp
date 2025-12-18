// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/xrio/headtracker.hpp"

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
  base_space_(handles.space)
{
    // Create VIEW space for head tracking (represents HMD pose)
    XrReferenceSpaceCreateInfo create_info{ XR_TYPE_REFERENCE_SPACE_CREATE_INFO };
    create_info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW;
    create_info.poseInReferenceSpace.orientation.w = 1.0f;

    view_space_ = createReferenceSpace(core_funcs_, handles.session, &create_info);

    head_.is_valid = false;
    head_.timestamp = 0;

    std::cout << "HeadTracker initialized" << std::endl;
}

HeadTracker::Impl::~Impl()
{
    // Smart pointer automatically cleans up view_space_
}

// Override from ITrackerImpl
bool HeadTracker::Impl::update(XrTime time)
{
    // Locate the view space (head) relative to the base space
    XrSpaceLocation location{ XR_TYPE_SPACE_LOCATION };
    XrResult result = core_funcs_.xrLocateSpace(*view_space_, base_space_, time, &location);

    if (XR_FAILED(result))
    {
        head_.is_valid = false;
        return false;
    }

    // Check if tracking is valid
    bool position_valid = (location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) != 0;
    bool orientation_valid = (location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT) != 0;

    head_.is_valid = position_valid && orientation_valid;
    head_.timestamp = time;

    if (head_.is_valid)
    {
        // Copy position
        head_.position[0] = location.pose.position.x;
        head_.position[1] = location.pose.position.y;
        head_.position[2] = location.pose.position.z;

        // Copy orientation
        head_.orientation[0] = location.pose.orientation.x;
        head_.orientation[1] = location.pose.orientation.y;
        head_.orientation[2] = location.pose.orientation.z;
        head_.orientation[3] = location.pose.orientation.w;
    }
    else
    {
        // Invalid - zero out
        memset(head_.position, 0, sizeof(head_.position));
        memset(head_.orientation, 0, sizeof(head_.orientation));
    }

    return true;
}

const HeadPose& HeadTracker::Impl::get_head() const
{
    return head_;
}

// ============================================================================
// HeadTracker Public Interface Implementation
// ============================================================================

HeadTracker::HeadTracker()
{
}

HeadTracker::~HeadTracker()
{
    // Session owns the impl, weak_ptr will detect if it's destroyed
}

std::vector<std::string> HeadTracker::get_required_extensions() const
{
    // Head tracking doesn't require special extensions - it's part of core OpenXR
    return {};
}

const HeadPose& HeadTracker::get_head() const
{
    static const HeadPose empty_pose{};
    auto impl = cached_impl_.lock();
    if (!impl)
        return empty_pose;
    return impl->get_head();
}

std::shared_ptr<ITrackerImpl> HeadTracker::initialize(const OpenXRSessionHandles& handles)
{
    auto shared = std::make_shared<Impl>(handles);
    cached_impl_ = shared;
    return shared;
}

bool HeadTracker::is_initialized() const
{
    return !cached_impl_.expired();
}

} // namespace core
