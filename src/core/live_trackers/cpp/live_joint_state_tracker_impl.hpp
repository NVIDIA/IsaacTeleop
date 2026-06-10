// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/joint_state_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/joint_state_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using JointStateMcapChannels = McapTrackerChannels<JointStateOutputRecord, JointStateOutput>;
using JointStateSchemaTracker = SchemaTracker<JointStateOutputRecord, JointStateOutput>;

class LiveJointStateTrackerImpl : public IJointStateTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<JointStateMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                        std::string_view base_name);

    LiveJointStateTrackerImpl(const OpenXRSessionHandles& handles,
                              const JointStateTracker* tracker,
                              std::unique_ptr<JointStateMcapChannels> mcap_channels);

    LiveJointStateTrackerImpl(const LiveJointStateTrackerImpl&) = delete;
    LiveJointStateTrackerImpl& operator=(const LiveJointStateTrackerImpl&) = delete;
    LiveJointStateTrackerImpl(LiveJointStateTrackerImpl&&) = delete;
    LiveJointStateTrackerImpl& operator=(LiveJointStateTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const JointStateOutputTrackedT& get_data() const override;

private:
    std::unique_ptr<JointStateMcapChannels> mcap_channels_;
    JointStateSchemaTracker m_schema_reader;
    JointStateOutputTrackedT m_tracked;
};

} // namespace core
