// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "controller_se3_tracker_plugin.hpp"

#include <deviceio_trackers/se3_tracker.hpp>
#include <flatbuffers/flatbuffers.h>
#include <oxr_utils/os_time.hpp>
#include <schema/controller_generated.h>
#include <schema/se3_tracker_generated.h>

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <vector>

namespace plugins
{
namespace controller_se3_tracker
{

namespace
{

std::vector<std::string> make_required_extensions(const std::vector<std::shared_ptr<core::ITracker>>& trackers)
{
    auto extensions = core::DeviceIOSession::get_required_extensions(trackers);
    for (const auto& ext : core::SchemaPusher::get_required_extensions())
    {
        if (std::find(extensions.begin(), extensions.end(), ext) == extensions.end())
        {
            extensions.push_back(ext);
        }
    }
    return extensions;
}

core::SchemaPusherConfig make_pusher_config(const std::string& collection_id)
{
    // Wire rendezvous (tensor identifier + buffer size) comes from the Se3Tracker facade —
    // the single source of truth shared with LiveSe3TrackerImpl; a mismatch is silent no-data.
    return core::SchemaPusherConfig{ .collection_id = collection_id,
                                     .max_flatbuffer_size = core::Se3Tracker::DEFAULT_MAX_FLATBUFFER_SIZE,
                                     .tensor_identifier = std::string(core::Se3Tracker::TENSOR_IDENTIFIER),
                                     .localized_name = "Controller SE3 Tracker",
                                     .app_name = "ControllerSe3TrackerPlugin" };
}

} // namespace

ControllerSe3TrackerPlugin::ControllerSe3TrackerPlugin(bool use_left_hand, const std::string& collection_id)
    : m_use_left_hand(use_left_hand)
{
    m_controller_tracker = std::make_shared<core::ControllerTracker>();
    std::vector<std::shared_ptr<core::ITracker>> trackers = { m_controller_tracker };

    m_session = std::make_shared<core::OpenXRSession>("ControllerSe3TrackerPlugin", make_required_extensions(trackers));
    const auto handles = m_session->get_handles();

    m_deviceio_session = core::DeviceIOSession::run(trackers, handles);
    m_pusher = std::make_unique<core::SchemaPusher>(handles, make_pusher_config(collection_id));

    std::cout << "ControllerSe3TrackerPlugin: republishing " << (m_use_left_hand ? "left" : "right")
              << " controller grip pose on collection '" << collection_id << "'" << std::endl;
}

void ControllerSe3TrackerPlugin::update()
{
    // Capture the sample time BEFORE update(): DeviceIOSession::update() samples
    // os_monotonic_now_ns() internally and locates the controller pose at that tick
    // (deviceio_session.cpp). The pre-update capture approximates that tick time to
    // microseconds; do not move this to post-update/push time — that would add loop
    // processing bias to cross-device synchronization.
    const int64_t sample_time_ns = core::os_monotonic_now_ns();

    m_deviceio_session->update();

    const core::ControllerSnapshotTrackedT& tracked =
        m_use_left_hand ? m_controller_tracker->get_left_controller(*m_deviceio_session) :
                          m_controller_tracker->get_right_controller(*m_deviceio_session);

    core::Se3TrackerPoseT out;
    if (tracked.data && tracked.data->grip_pose && tracked.data->grip_pose->is_valid())
    {
        out.pose = std::make_shared<core::Pose>(tracked.data->grip_pose->pose());
        out.is_valid = true;
    }
    else
    {
        // Identity pose is a filler consistent with "pose contents unspecified when
        // is_valid == false" (se3_tracker.fbs) — consumers gate on is_valid, never on
        // pose values. Pushing explicit invalidity beats silence, which is ambiguous
        // both live (stale retention) and in recordings.
        out.pose = std::make_shared<core::Pose>(core::Point(0.0f, 0.0f, 0.0f), core::Quaternion(0.0f, 0.0f, 0.0f, 1.0f));
        out.is_valid = false;
    }

    flatbuffers::FlatBufferBuilder builder(core::Se3Tracker::DEFAULT_MAX_FLATBUFFER_SIZE);
    auto offset = core::Se3TrackerPose::Pack(builder, &out);
    builder.Finish(offset);

    // A logical device has no raw device clock of its own; pass the local common clock
    // sample time as the documented best-effort substitute.
    m_pusher->push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

} // namespace controller_se3_tracker
} // namespace plugins
