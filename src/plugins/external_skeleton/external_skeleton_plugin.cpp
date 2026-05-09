// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "external_skeleton_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/external_skeleton_generated.h>

#include <stdexcept>
#include <utility>

namespace plugins
{
namespace external_skeleton
{

namespace
{

// Sized for 14 BodyJointPose entries + flags + a short source_id string.
// Mirrors ExternalSkeletonTracker::DEFAULT_MAX_FLATBUFFER_SIZE; both ends must
// agree on a size at least this large for SchemaPusher to accept the buffer.
constexpr size_t kMaxFlatbufferSize = 2048;

} // namespace

ExternalSkeletonPlugin::ExternalSkeletonPlugin(std::unique_ptr<IExternalSkeletonSource> source,
                                               const std::string& collection_id)
    : source_(std::move(source)),
      session_(std::make_shared<core::OpenXRSession>(
          "ExternalSkeletonPlugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "external_skeleton_pose",
                                        .localized_name = "External Skeleton",
                                        .app_name = "ExternalSkeletonPlugin" }),
      max_flatbuffer_size_(kMaxFlatbufferSize)
{
    if (!source_)
    {
        throw std::invalid_argument("ExternalSkeletonPlugin: source must not be null");
    }
}

void ExternalSkeletonPlugin::update()
{
    core::ExternalSkeletonPoseT pose;
    int64_t raw_device_clock_ns = 0;
    if (!source_->poll(pose, raw_device_clock_ns))
    {
        return;
    }
    push(pose, raw_device_clock_ns);
}

void ExternalSkeletonPlugin::push(const core::ExternalSkeletonPoseT& pose, int64_t raw_device_clock_ns)
{
    const int64_t sample_time_local_common_clock_ns = core::os_monotonic_now_ns();
    if (raw_device_clock_ns == 0)
    {
        // Device did not report its own clock; substitute the local monotonic
        // clock as documented in SchemaPusher::push_buffer.
        raw_device_clock_ns = sample_time_local_common_clock_ns;
    }

    flatbuffers::FlatBufferBuilder builder(max_flatbuffer_size_);
    auto offset = core::ExternalSkeletonPose::Pack(builder, &pose);
    builder.Finish(offset);
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_local_common_clock_ns,
                        raw_device_clock_ns);
}

} // namespace external_skeleton
} // namespace plugins
