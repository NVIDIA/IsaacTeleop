// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "controller_se3_tracker_plugin.hpp"

#include <deviceio_trackers/se3_tracker.hpp>
#include <flatbuffers/flatbuffers.h>
#include <oxr_utils/os_time.hpp>
#include <schema/controller_generated.h>
#include <schema/se3_tracker_generated.h>

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <utility>

namespace plugins
{
namespace controller_se3_tracker
{

namespace
{

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

ControllerSe3TrackerPlugin::ControllerSe3TrackerPlugin(bool use_left_hand,
                                                       const std::string& collection_id,
                                                       std::shared_ptr<core::ControllerTracker> controller_tracker,
                                                       core::PluginSessionHandle plugin_session)
    : m_use_left_hand(use_left_hand),
      m_controller_tracker(std::move(controller_tracker)),
      m_plugin_session(std::move(plugin_session))
{
    if (!m_controller_tracker || !m_plugin_session)
    {
        throw std::invalid_argument("ControllerSe3TrackerPlugin requires a controller tracker and plugin session");
    }
    m_pull_channel = m_plugin_session->create_pull_channel();
    if (!m_pull_channel)
    {
        throw std::runtime_error("The plugin session could not create a pull channel");
    }
    m_pusher = std::make_unique<core::SchemaPusher>(
        m_plugin_session->create_schema_push_channel(make_pusher_config(collection_id)));

    std::cout << "ControllerSe3TrackerPlugin: republishing " << (m_use_left_hand ? "left" : "right")
              << " controller grip pose on collection '" << collection_id << "'" << std::endl;
}

void ControllerSe3TrackerPlugin::update()
{
    // Capture before update so the output timestamp approximates the pull
    // channel's polling tick instead of including this loop's processing time.
    const int64_t sample_time_ns = core::os_monotonic_now_ns();

    m_pull_channel->update();

    const core::Serialized<core::ControllerSnapshot>& tracked =
        m_use_left_hand ? m_controller_tracker->get_left_controller(*m_pull_channel) :
                          m_controller_tracker->get_right_controller(*m_pull_channel);

    const core::ControllerSnapshot* snapshot = tracked.get();

    core::Se3TrackerPoseT out;
    if (snapshot != nullptr && snapshot->grip_pose() != nullptr && snapshot->grip_pose()->is_valid())
    {
        out.pose = std::make_shared<core::Pose>(snapshot->grip_pose()->pose());
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
