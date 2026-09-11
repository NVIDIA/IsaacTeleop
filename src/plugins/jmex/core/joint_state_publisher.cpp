// SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/jmex/joint_state_publisher.hpp"

#include "inc/jmex/receiver_session.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr_utils/os_time.hpp>
#include <schema/joint_state_generated.h>

#include <iostream>
#include <memory>

namespace plugins
{
namespace jmex
{

JointStatePublisher::JointStatePublisher(const core::OpenXRSessionHandles& handles, const std::string& collection_id)
    : collection_id_(collection_id),
      pusher_(handles,
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = MAX_FLATBUFFER_SIZE,
                                        // Must match what JointStateTracker reads.
                                        .tensor_identifier = "joint_state",
                                        .localized_name = "j-mex AgileMaster",
                                        .app_name = "JmexPlugin" })
{
}

void JointStatePublisher::publish(const ReceiverSession& receiver)
{
    core::JointStateOutputT out;
    out.device_id = collection_id_;
    out.has_velocity = true; // the SDK reports angular velocity per joint at no extra cost
    out.has_effort = false;
    out.ee_pose_valid = false; // no device-side FK; the retargeter computes it when it needs it

    for (const auto& joint : receiver.actuated_joints())
    {
        auto entry = std::make_shared<core::JointStateT>();
        entry->name = joint.name;
        entry->position = receiver.angle(joint);
        entry->velocity = receiver.angular_velocity(joint);
        entry->valid = true;
        out.joints.push_back(std::move(entry));
    }

    // Player carries no device clock -- the sequence id is a counter, not a timestamp -- so the local
    // common clock is the only real one we have and it stands in for both.
    const auto sample_time_ns = core::os_monotonic_now_ns();

    flatbuffers::FlatBufferBuilder builder(MAX_FLATBUFFER_SIZE);
    auto offset = core::JointStateOutput::Pack(builder, &out);
    builder.Finish(offset);

    if (builder.GetSize() > MAX_FLATBUFFER_SIZE)
    {
        // Report it: a silent drop would look like Player stopping.
        std::cerr << "jmex: serialized JointStateOutput is " << builder.GetSize() << " bytes, over the "
                  << MAX_FLATBUFFER_SIZE << "-byte budget shared with the consumer's JointStateTracker ("
                  << out.joints.size() << " joints). Sample dropped." << std::endl;
        return;
    }

    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

} // namespace jmex
} // namespace plugins
